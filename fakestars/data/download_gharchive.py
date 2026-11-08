"""No-cloud alternative: download hourly GH Archive files and keep only the 7 columns we need.

Writes one parquet per day to cfg.data.raw_dir/events/YYYY-MM-DD.parquet (resumable).
Best for short pilots (days/weeks); use BigQuery for the full quarter.
"""
from __future__ import annotations

import gzip
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

from ..config import window
from ..utils import log
from .schema import RAW_COLUMNS

URL = "https://data.gharchive.org/{day}-{hour}.json.gz"


def _hour(day: str, hour: int, session: requests.Session) -> list[tuple]:
    url = URL.format(day=day, hour=hour)
    for attempt in range(3):
        try:
            r = session.get(url, timeout=300)
            if r.status_code == 404:
                log.warning("missing %s", url)
                return []
            r.raise_for_status()
            break
        except requests.RequestException as e:
            if attempt == 2:
                raise
            log.warning("retry %s (%s)", url, e)
    rows = []
    for line in gzip.decompress(r.content).splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue  # malformed line: skipped, counted by build as absent
        a, rp = e.get("actor") or {}, e.get("repo") or {}
        rows.append((e.get("id"), e.get("type"), a.get("id"), a.get("login"),
                     rp.get("id"), rp.get("name"), e.get("created_at")))
    return rows


def download(cfg: dict) -> None:
    start, end_excl = window(cfg)
    out = Path(cfg["data"]["raw_dir"]) / "events"
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = "fakestars-research-pipeline"
    workers = cfg["extraction"].get("gharchive_workers", 4)
    for day in pd.date_range(start, end_excl - pd.Timedelta(days=1), freq="D"):
        d = day.strftime("%Y-%m-%d")
        target = out / f"{d}.parquet"
        if target.exists():
            log.info("skip %s (exists)", d)
            continue
        with ThreadPoolExecutor(workers) as ex:
            parts = list(ex.map(lambda h: _hour(d, h, session), range(24)))
        df = pd.DataFrame([r for p in parts for r in p], columns=RAW_COLUMNS)
        df["event_id"] = df["event_id"].astype("string")
        df["actor_id"] = pd.to_numeric(df["actor_id"], errors="coerce").astype("Int64")
        df["repo_id"] = pd.to_numeric(df["repo_id"], errors="coerce").astype("Int64")
        df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce", utc=True).dt.tz_localize(None)
        df.to_parquet(target, index=False)
        log.info("%s: %d events", d, len(df))
