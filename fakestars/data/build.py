"""Preprocessing: quality checks, deduplication, and the canonical local database.

Input (cfg.data.raw_dir), one of:
  events mode   : events/*.parquet                     (GH Archive download or synthetic data)
  bigquery mode : stars/*.parquet + actor_profile.parquet + small_actor_events.parquet

Output DuckDB tables (cfg.data.processed_db):
  stars(actor_id, repo_id, ts, n_star_events)   one row per (account, repository), first star time
  actor_profile(...)                             activity counts for every stargazer
  small_events(event_id, actor_id, repo_id, type, created_at)
  repo_names(repo_id, repo_name), actor_logins(actor_id, login)
and results/<run>/data_quality.json with counts before/after every filter.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from ..config import results_dir, window
from ..utils import log, write_json
from .schema import KNOWN_EVENT_TYPES, PROFILE_GROUPS, STAR

_TYPES = ", ".join(f"'{t}'" for t in KNOWN_EVENT_TYPES)
_DEDUP_KEY = ("COALESCE(CAST(event_id AS VARCHAR), CAST(actor_id AS VARCHAR) || '|' || "
              "CAST(repo_id AS VARCHAR) || '|' || type || '|' || CAST(created_at AS VARCHAR))")


def _count(con, table: str) -> int:
    return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _clean(con, src: str, dst: str, q: dict, start, end_excl, prefix: str) -> None:
    """Quality filters + dedup, logging counts after each step."""
    q[f"{prefix}raw_rows"] = _count(con, src)
    con.execute(f"""CREATE OR REPLACE TEMP TABLE _s1 AS SELECT * FROM {src}
                    WHERE actor_id IS NOT NULL AND repo_id IS NOT NULL AND type IS NOT NULL""")
    q[f"{prefix}removed_missing_ids"] = q[f"{prefix}raw_rows"] - _count(con, "_s1")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE _s2 AS SELECT * FROM _s1
                    WHERE created_at IS NOT NULL AND created_at >= TIMESTAMP '{start}'
                      AND created_at < TIMESTAMP '{end_excl}'""")
    q[f"{prefix}removed_invalid_timestamp"] = _count(con, "_s1") - _count(con, "_s2")
    unexpected = con.execute(f"SELECT type, COUNT(*) FROM _s2 WHERE type NOT IN ({_TYPES}) GROUP BY 1").fetchall()
    q[f"{prefix}unexpected_types"] = {t: n for t, n in unexpected}
    con.execute(f"CREATE OR REPLACE TEMP TABLE _s3 AS SELECT * FROM _s2 WHERE type IN ({_TYPES})")
    q[f"{prefix}removed_unexpected_type"] = sum(q[f"{prefix}unexpected_types"].values())
    q[f"{prefix}rows_without_event_id"] = con.execute("SELECT COUNT(*) FROM _s3 WHERE event_id IS NULL").fetchone()[0]
    # Deduplicate on event id; rows without an id fall back to a composite key.
    con.execute(f"""CREATE OR REPLACE TABLE {dst} AS
        SELECT * EXCLUDE (_k, _rn) FROM (
          SELECT *, ROW_NUMBER() OVER (PARTITION BY _k ORDER BY created_at) AS _rn
          FROM (SELECT *, {_DEDUP_KEY} AS _k FROM _s3)
        ) WHERE _rn = 1""")
    q[f"{prefix}removed_duplicates"] = _count(con, "_s3") - _count(con, dst)
    q[f"{prefix}clean_rows"] = _count(con, dst)


def _profile_sql(src: str) -> str:
    cols = ",\n".join(
        f"COUNT(*) FILTER (WHERE type IN ({', '.join(repr(t) for t in ts)})) AS {name}"
        for name, ts in PROFILE_GROUPS.items())
    return f"""SELECT actor_id, COUNT(*) AS n_events,
                      COUNT(*) FILTER (WHERE type = '{STAR}') AS n_watch,
                      {cols}, MIN(created_at) AS first_ts, MAX(created_at) AS last_ts
               FROM {src} WHERE actor_id IN (SELECT DISTINCT actor_id FROM stars)
               GROUP BY actor_id"""


def build(cfg: dict) -> dict:
    raw = Path(cfg["data"]["raw_dir"])
    db = Path(cfg["data"]["processed_db"])
    db.parent.mkdir(parents=True, exist_ok=True)
    if db.exists():
        db.unlink()
    start, end_excl = window(cfg)
    k = cfg["data"]["small_actor_max_other_events"]
    q: dict = {"window": [str(start), str(end_excl)]}
    con = duckdb.connect(str(db))

    if (raw / "events").exists():
        q["mode"] = "events"
        con.execute(f"CREATE VIEW raw AS SELECT * FROM read_parquet('{raw.as_posix()}/events/*.parquet', union_by_name=true)")
        q["raw_files"] = len(list((raw / "events").glob("*.parquet")))
        _clean(con, "raw", "events", q, start, end_excl, "")
        con.execute(f"CREATE TABLE star_events AS SELECT * FROM events WHERE type = '{STAR}'")
    elif (raw / "stars").exists():
        q["mode"] = "bigquery"
        con.execute(f"CREATE VIEW raw AS SELECT * FROM read_parquet('{raw.as_posix()}/stars/*.parquet', union_by_name=true)")
        q["raw_files"] = len(list((raw / "stars").glob("*.parquet")))
        _clean(con, "raw", "star_events", q, start, end_excl, "")
    else:
        raise SystemExit(f"No raw data in {raw}: run `extract-bq`, `extract-gha` or `synth` first")

    con.execute("""CREATE TABLE stars AS
        SELECT actor_id, repo_id, MIN(created_at) AS ts, COUNT(*) AS n_star_events
        FROM star_events GROUP BY actor_id, repo_id""")
    q["star_events"] = _count(con, "star_events")
    q["restar_events_collapsed"] = q["star_events"] - _count(con, "stars")

    if q["mode"] == "events":
        con.execute("CREATE TABLE actor_profile AS " + _profile_sql("events"))
        con.execute(f"""CREATE TABLE small_events AS
            SELECT e.event_id, e.actor_id, e.repo_id, e.type, e.created_at
            FROM events e JOIN actor_profile p USING (actor_id)
            WHERE e.type <> '{STAR}' AND p.n_events - p.n_watch <= {k}""")
        src_names = "events"
    else:
        con.execute(f"CREATE TABLE actor_profile AS SELECT * FROM read_parquet('{raw.as_posix()}/actor_profile.parquet')")
        con.execute(f"CREATE VIEW raw_small AS SELECT * FROM read_parquet('{raw.as_posix()}/small_actor_events.parquet')")
        _clean(con, "raw_small", "small_events", q, start, end_excl, "small_events_")
        src_names = "star_events"

    con.execute(f"""CREATE TABLE repo_names AS SELECT repo_id, arg_max(repo_name, created_at) AS repo_name
                    FROM {src_names} WHERE repo_name IS NOT NULL GROUP BY repo_id""")
    con.execute(f"""CREATE TABLE actor_logins AS SELECT actor_id, arg_max(actor_login, created_at) AS login
                    FROM {src_names} WHERE actor_login IS NOT NULL
                      AND actor_id IN (SELECT actor_id FROM stars) GROUP BY actor_id""")
    q["unique_star_edges"] = _count(con, "stars")
    q["unique_accounts"] = con.execute("SELECT COUNT(DISTINCT actor_id) FROM stars").fetchone()[0]
    q["unique_repositories"] = con.execute("SELECT COUNT(DISTINCT repo_id) FROM stars").fetchone()[0]
    q["profiled_accounts"] = _count(con, "actor_profile")
    q["small_event_rows"] = _count(con, "small_events")
    if q["mode"] == "events":
        con.execute("DROP TABLE events")  # keep the database small
        con.execute("DROP TABLE star_events")
    con.close()
    write_json(results_dir(cfg) / "data_quality.json", q)
    log.info("build: %d unique stars, %d accounts, %d repos -> %s",
             q["unique_star_edges"], q["unique_accounts"], q["unique_repositories"], db)
    return q


def load_tables(cfg: dict) -> dict[str, pd.DataFrame]:
    con = duckdb.connect(cfg["data"]["processed_db"], read_only=True)
    out = {t: con.execute(f"SELECT * FROM {t}").df() for t in
           ["stars", "actor_profile", "small_events", "repo_names", "actor_logins"]}
    con.close()
    for t in out.values():
        for c in t.columns:
            if c in ("actor_id", "repo_id"):
                t[c] = t[c].astype("int64")
    return out
