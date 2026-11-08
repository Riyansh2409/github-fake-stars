import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

T0 = pd.Timestamp("2024-01-01")


def ts(days: float) -> pd.Timestamp:
    return T0 + pd.Timedelta(days=days)


def edges(rows) -> pd.DataFrame:
    """rows: iterable of (actor_id, repo_id, day_offset)."""
    df = pd.DataFrame(list(rows), columns=["actor_id", "repo_id", "day"])
    df["ts"] = T0 + pd.to_timedelta(df.pop("day"), unit="D")
    return df.drop_duplicates(["actor_id", "repo_id"]).reset_index(drop=True)


def planted_group(n_acc=60, n_repo=12, share=0.7, spread_days=5, seed=0, actor0=1000, repo0=500,
                  window_gap_days=6):
    """Each repo gets stars from `share` of a pool, delivered within `spread_days`."""
    rng = np.random.default_rng(seed)
    pool = np.arange(actor0, actor0 + n_acc)
    rows = []
    for j in range(n_repo):
        start = j * window_gap_days
        for a in rng.choice(pool, int(round(share * n_acc)), replace=False):
            rows.append((int(a), repo0 + j, start + rng.uniform(0, spread_days)))
    return rows


def noise(n_actors=400, n_repos=300, n_stars=3000, days=90, seed=1, actor0=100_000, repo0=10_000):
    rng = np.random.default_rng(seed)
    return [(int(actor0 + rng.integers(n_actors)), int(repo0 + rng.integers(n_repos)), rng.uniform(0, days))
            for _ in range(n_stars)]
