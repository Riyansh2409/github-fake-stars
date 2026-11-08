"""Detection pipeline: Signal 1 + Signal 2 -> union -> filtering, with timing and memory."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import results_dir
from .detection.copycatch import LockstepParams, detect_lockstep
from .detection.filtering import filter_campaigns
from .detection.low_activity import low_activity_signal
from .utils import log, manifest, peak_rss_mb, read_json, stopwatch, write_json


def lockstep_signal(stars: pd.DataFrame, lcfg: dict):
    """Runs CopyCatch on the full window, or on overlapping time chunks (lockstep.chunk_days)."""
    params = LockstepParams.from_cfg(lcfg)
    chunk = lcfg.get("chunk_days")
    if not chunk:
        return detect_lockstep(stars, params)
    step, ov = pd.Timedelta(days=chunk), pd.Timedelta(days=lcfg.get("chunk_overlap_days", 30))
    lo, end = stars.ts.min(), stars.ts.max()
    edges, groups, stats = [], [], {"chunks": []}
    while lo <= end:
        sub = stars[(stars.ts >= lo) & (stars.ts < lo + step + ov)]
        e, g, s = detect_lockstep(sub, params)
        edges.append(e)
        groups += g
        stats["chunks"].append({"start": str(lo), **s})
        lo += step
    flagged = pd.concat(edges).drop_duplicates(["actor_id", "repo_id"]).reset_index(drop=True)
    stats.update(groups=len(groups), flagged_edges=int(len(flagged)))
    return flagged, groups, stats


def union_edges(*frames: pd.DataFrame) -> pd.DataFrame:
    frames = [f for f in frames if f is not None and not f.empty]
    if not frames:
        return pd.DataFrame(columns=["actor_id", "repo_id", "ts"])
    return pd.concat(frames).drop_duplicates(["actor_id", "repo_id"]).reset_index(drop=True)


def run_detection(cfg: dict, data: dict) -> dict:
    stars, prof, small = data["stars"], data["actor_profile"], data["small_events"]
    timings: dict = {}
    la, fc = cfg["low_activity"], cfg["filtering"]
    with stopwatch(timings, "low_activity_s"):
        low, low_stats = low_activity_signal(stars, prof, small, la["max_other_events"], la["repo_min_stars"])
    with stopwatch(timings, "lockstep_s"):
        lock, groups, lock_stats = lockstep_signal(stars, cfg["lockstep"])
    union = union_edges(low, lock)
    with stopwatch(timings, "filtering_s"):
        repos, actors = filter_campaigns(stars, union, fc["spike_min_stars"], fc["spike_min_share"],
                                         fc["alltime_min_share"])
    summary = {
        "events": {"unique_star_edges": int(len(stars)), "accounts": int(stars.actor_id.nunique()),
                   "repositories": int(stars.repo_id.nunique())},
        "low_activity": low_stats,
        "lockstep": {k: v for k, v in lock_stats.items() if k != "chunks"},
        "before_filtering": {"flagged_stars_low": int(len(low)), "flagged_stars_lockstep": int(len(lock)),
                             "flagged_stars_union": int(len(union)),
                             "flagged_stars_both": int(len(low) + len(lock) - len(union)),
                             "flagged_repos": int(union.repo_id.nunique()),
                             "flagged_accounts": int(union.actor_id.nunique())},
        "after_filtering": {"campaign_repos": int(len(repos)),
                            "campaign_participants": int(actors.actor_id.nunique()),
                            "flagged_participants": int(actors[actors.flagged_participant].actor_id.nunique())
                            if len(actors) else 0},
        "runtime_s": timings, "peak_memory_mb": peak_rss_mb(),
    }
    return {"low": low, "lock": lock, "union": union, "groups": groups, "repos": repos,
            "actors": actors, "summary": summary, "lock_stats": lock_stats}


def save_detection(cfg: dict, res: dict) -> Path:
    out = results_dir(cfg)
    det = out / "detections"  # account/repo identifiers: kept local, git-ignored
    det.mkdir(exist_ok=True)
    res["low"].to_parquet(det / "flagged_low_activity.parquet", index=False)
    res["lock"].to_parquet(det / "flagged_lockstep.parquet", index=False)
    res["repos"].to_parquet(det / "campaign_repos.parquet", index=False)
    res["actors"].to_parquet(det / "campaign_participants.parquet", index=False)
    write_json(det / "lockstep_groups.json", res["groups"])
    # Aggregate-only outputs (safe to publish)
    write_json(out / "detection_summary.json", res["summary"])
    write_json(out / "lockstep_groups_summary.json",
               [{k: v for k, v in g.items() if k not in ("account_ids", "repo_ids")} for g in res["groups"]])
    write_json(out / "run_manifest.json", manifest(cfg))
    log.info("detection: %s", res["summary"]["after_filtering"])
    return out


def load_detection(cfg: dict) -> dict:
    det = results_dir(cfg) / "detections"
    if not det.exists():
        raise SystemExit("No detections found: run `python -m fakestars detect` first")
    return {"low": pd.read_parquet(det / "flagged_low_activity.parquet"),
            "lock": pd.read_parquet(det / "flagged_lockstep.parquet"),
            "repos": pd.read_parquet(det / "campaign_repos.parquet"),
            "actors": pd.read_parquet(det / "campaign_participants.parquet"),
            "groups": read_json(det / "lockstep_groups.json"),
            "summary": read_json(results_dir(cfg) / "detection_summary.json")}
