"""Comparison samples: a random repository baseline and one matched by size and age.

Matching uses what the event sample itself offers: star-count range (log2 bin of stars in the
window) and an age proxy (month of the repository's first observed star in the window).
Fallbacks when a cell is too small: same size bin any month, then adjacent size bins.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def repo_features(stars: pd.DataFrame) -> pd.DataFrame:
    f = stars.groupby("repo_id").agg(n_stars=("ts", "size"), first_ts=("ts", "min"))
    f["size_bin"] = np.floor(np.log2(f.n_stars)).astype(int)
    f["age_bin"] = f.first_ts.dt.to_period("M").astype(str)
    return f


def random_repos(feat: pd.DataFrame, exclude, size: int, seed: int) -> list:
    pool = feat.index.difference(pd.Index(list(exclude)))
    size = min(size, len(pool))
    return sorted(np.random.default_rng(seed).choice(pool.to_numpy(), size, replace=False).tolist())


def matched_repos(feat: pd.DataFrame, targets, exclude, seed: int) -> list:
    rng = np.random.default_rng(seed)
    pool = feat.drop(index=feat.index.intersection(pd.Index(list(exclude) + list(targets))))
    want = feat.loc[feat.index.intersection(pd.Index(list(targets)))]
    chosen: set = set()
    for (sb, ab), grp in want.groupby(["size_bin", "age_bin"]):
        need = len(grp)
        for cand in (pool[(pool.size_bin == sb) & (pool.age_bin == ab)], pool[pool.size_bin == sb],
                     pool[(pool.size_bin - sb).abs() <= 1]):
            cand = cand.index.difference(pd.Index(list(chosen)))
            take = min(need, len(cand))
            if take:
                chosen.update(rng.choice(cand.to_numpy(), take, replace=False).tolist())
                need -= take
            if need == 0:
                break
    return sorted(chosen)


def random_actors(stars: pd.DataFrame, exclude, size: int, seed: int) -> list:
    pool = pd.Index(stars.actor_id.unique()).difference(pd.Index(list(exclude)))
    size = min(size, len(pool))
    return sorted(np.random.default_rng(seed).choice(pool.to_numpy(), size, replace=False).tolist())
