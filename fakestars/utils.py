"""Logging, timing, memory, JSON and statistics helpers."""
from __future__ import annotations

import json
import logging
import math
import platform
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import psutil

log = logging.getLogger("fakestars")


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(message)s",
        datefmt="%H:%M:%S",
    )


def peak_rss_mb() -> float:
    """Peak resident memory of this process in MB (best effort, cross-platform)."""
    mi = psutil.Process().memory_info()
    peak = getattr(mi, "peak_wset", None)  # Windows
    if peak:
        return round(peak / 2**20, 1)
    try:
        import resource

        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(r / 2**20 if sys.platform == "darwin" else r / 1024, 1)
    except ImportError:
        return round(mi.rss / 2**20, 1)


@contextmanager
def stopwatch(store: dict, key: str):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        store[key] = round(time.perf_counter() - t0, 3)


def _default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if math.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, Path):
        return str(o)
    return str(o)


def write_json(path: str | Path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=_default))


def read_json(path: str | Path):
    return json.loads(Path(path).read_text())


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """Proportion with Wilson 95% interval."""
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    p = k / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return p, max(0.0, centre - half), min(1.0, centre + half)


def diff_ci(k1: int, n1: int, k2: int, n2: int, z: float = 1.96) -> tuple[float, float, float]:
    """Difference of proportions p1 - p2 with Newcombe (Wilson-based) 95% interval."""
    if n1 == 0 or n2 == 0:
        return float("nan"), float("nan"), float("nan")
    p1, l1, u1 = wilson(k1, n1, z)
    p2, l2, u2 = wilson(k2, n2, z)
    d = p1 - p2
    lo = d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    hi = d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return d, lo, hi


def _pkg_version(name: str) -> str | None:
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:
        return None


def manifest(cfg: dict) -> dict:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5
        ).stdout.strip() or None
    except Exception:
        commit = None
    return {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": commit,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packages": {p: _pkg_version(p) for p in
                     ["numpy", "pandas", "pyarrow", "duckdb", "scipy", "matplotlib", "google-cloud-bigquery"]},
        "config": {k: v for k, v in cfg.items() if not k.startswith("_")},
        "config_path": cfg.get("_config_path"),
    }
