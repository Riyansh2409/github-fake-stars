"""Extract the sample from GH Archive's public BigQuery tables.

Outputs (in cfg.data.raw_dir):
  stars/part-XXX.parquet      star events, in overlapping time chunks (dedup happens in `build`)
  actor_profile.parquet       per-stargazer activity counts (all event types)
  small_actor_events.parquet  non-star events of near-inactive stargazers (for the low-activity rule)

Run with --dry-run first: it prints the bytes each query would scan (the pilot cost check).
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from ..config import window
from ..utils import log, write_json

SQL_DIR = Path(__file__).resolve().parents[2] / "sql" / "bigquery"
PRICE_PER_TIB = 6.25  # USD, on-demand; first 1 TiB per month is free


def _suffix(ts: pd.Timestamp) -> str:
    return ts.strftime("%y%m%d")


def _sql(name: str, **kw) -> str:
    return (SQL_DIR / name).read_text().format(**kw)


def _chunks(cfg):
    start, end_excl = window(cfg)
    end = end_excl - pd.Timedelta(days=1)
    step = pd.Timedelta(days=cfg["extraction"]["chunk_days"])
    ov = pd.Timedelta(days=cfg["extraction"]["overlap_days"])
    out, lo = [], start
    while lo <= end:
        hi = min(lo + step - pd.Timedelta(days=1) + ov, end)
        out.append((max(start, lo - ov), hi))
        lo = lo + step
    return out


def _naive_utc(df: pd.DataFrame) -> pd.DataFrame:
    for c in df.columns:
        if isinstance(df[c].dtype, pd.DatetimeTZDtype):
            df[c] = df[c].dt.tz_convert("UTC").dt.tz_localize(None)
    return df


def extract(cfg: dict, dry_run: bool = False) -> dict:
    try:
        from google.cloud import bigquery
    except ImportError as e:  # pragma: no cover
        raise SystemExit("pip install -r requirements-bigquery.txt  (google-cloud-bigquery)") from e

    project = cfg["extraction"].get("bq_project") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    client = bigquery.Client(project=project)
    cap = int(cfg["extraction"]["max_gb_billed"] * 1e9)
    start, end_excl = window(cfg)
    full = {"start_suffix": _suffix(start), "end_suffix": _suffix(end_excl - pd.Timedelta(days=1))}
    k = cfg["data"]["small_actor_max_other_events"]

    jobs = [(f"stars_{i:03d}", _sql("01_star_events.sql", start_suffix=_suffix(a), end_suffix=_suffix(b)))
            for i, (a, b) in enumerate(_chunks(cfg))]
    jobs += [("actor_profile", _sql("02_actor_profile.sql", **full)),
             ("small_actor_events", _sql("03_small_actor_events.sql", max_other=k, **full))]

    raw = Path(cfg["data"]["raw_dir"])
    (raw / "stars").mkdir(parents=True, exist_ok=True)
    report = {"queries": {}, "dry_run": dry_run}
    for name, sql in jobs:
        dry = client.query(sql, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False))
        gb = dry.total_bytes_processed / 1e9
        report["queries"][name] = {"estimated_gb": round(gb, 2)}
        log.info("%-20s would scan %.1f GB", name, gb)
        if dry_run:
            continue
        job = client.query(sql, job_config=bigquery.QueryJobConfig(maximum_bytes_billed=cap))
        df = _naive_utc(job.result().to_dataframe(create_bqstorage_client=True))
        out = raw / "stars" / f"part-{name[6:]}.parquet" if name.startswith("stars_") else raw / f"{name}.parquet"
        df.to_parquet(out, index=False)
        report["queries"][name].update(rows=len(df), billed_gb=round((job.total_bytes_billed or 0) / 1e9, 2))
        log.info("%-20s -> %s (%d rows)", name, out, len(df))

    total = sum(q["estimated_gb"] for q in report["queries"].values())
    report["total_estimated_gb"] = round(total, 2)
    report["estimated_cost_usd_beyond_free_tier"] = round(total / 1024 * PRICE_PER_TIB, 2)
    log.info("total scan %.1f GB (~$%.2f on-demand, free under 1 TiB/month)", total,
             report["estimated_cost_usd_beyond_free_tier"])
    write_json(raw / ("extraction_dryrun.json" if dry_run else "extraction_report.json"), report)
    return report
