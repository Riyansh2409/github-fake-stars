"""Signal 2 (proposal Section 3.2): lockstep behaviour via a CopyCatch-style local search.

Bipartite graph: accounts -- star(timestamp) -- repositories.
A group (U, P) with a window start c_p for every p in P is *lockstep* when
    |U| >= n, |P| >= m,
    every repository p receives stars from >= rho*|U| accounts of U inside [c_p, c_p + dt), and
    (user_side=True, as in the original CopyCatch [Beutel et al. 2013]) every account in U
    starred >= rho*|P| repositories of P inside their windows.
Windows of different repositories are independent (X can be in February, Y in May).

Exact search is intractable, so, like CopyCatch, we use a greedy alternating local search:
  0. prune edges that cannot belong to any lockstep group (necessary conditions, iterated);
  1. seed from the repository with the largest burst not yet covered by a found group;
  2. repo step   : for all repos touched by U, pick the densest window; keep those with >= rho*|U|;
  3. user step   : keep accounts hitting >= rho*|P| of those windows;
  4. repeat 2-3 until stable, then *peel* (shrink-only) until both conditions hold exactly;
  5. accept if |U| >= n and |P| >= m.
It is not guaranteed to find every group (see README, Limitations).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

EPS = 1e-9


@dataclass
class LockstepParams:
    n: int = 50
    m: int = 10
    rho: float = 0.5
    delta_t_days: float = 30
    user_side: bool = True
    max_iter: int = 15
    max_seeds: int = 3000

    @classmethod
    def from_cfg(cls, c: dict) -> "LockstepParams":
        return cls(**{k: c[k] for k in cls.__dataclass_fields__ if k in c})

    @property
    def dt(self) -> int:
        return int(self.delta_t_days * 86400)


# --------------------------------------------------------------------------- numpy helpers
def best_windows(repo: np.ndarray, t: np.ndarray, dt: int):
    """For each repository: the window [start, start+dt) holding the most edges.
    Returns (repos sorted, max count, window start)."""
    if len(repo) == 0:
        e = np.array([], dtype=np.int64)
        return e, e, e
    order = np.lexsort((t, repo))
    r, tt = repo[order].astype(np.int64), t[order].astype(np.int64)
    big = int(tt.max()) + dt + 1
    key = r * big + tt
    cnt = np.searchsorted(key, key + dt, side="left") - np.arange(len(key))
    o2 = np.lexsort((-cnt, r))
    r2 = r[o2]
    first = np.r_[True, r2[1:] != r2[:-1]]
    sel = o2[first]
    return r[sel], cnt[sel], tt[sel]


def _gather(ptr: np.ndarray, items: np.ndarray):
    """CSR gather: edge indices for `items`, and the position (in items) each edge belongs to."""
    starts = ptr[items]
    lens = ptr[items + 1] - starts
    total = int(lens.sum())
    if total == 0:
        return np.array([], dtype=np.int64), np.array([], dtype=np.int64)
    offs = np.repeat(starts - np.cumsum(np.r_[0, lens[:-1]]), lens)
    return offs + np.arange(total), np.repeat(np.arange(len(items)), lens)


class _Graph:
    def __init__(self, a, r, t, row, A, R):
        oa = np.lexsort((t, a))
        self.a_ptr = np.searchsorted(a[oa], np.arange(A + 1))
        self.a_repo, self.a_ts = r[oa], t[oa]
        orr = np.lexsort((t, r))
        self.r_ptr = np.searchsorted(r[orr], np.arange(R + 1))
        self.r_actor, self.r_ts, self.r_row = a[orr], t[orr], row[orr]
        self.A, self.R = A, R


def _prune(a, r, t, A, R, p: LockstepParams) -> np.ndarray:
    """Iteratively drop edges that cannot be part of any lockstep group."""
    min_repo = math.ceil(p.rho * p.n - EPS)
    min_user = math.ceil(p.rho * p.m - EPS) if p.user_side else 1
    keep = np.ones(len(a), bool)
    while True:
        reps, cnt, _ = best_windows(r[keep], t[keep], p.dt)
        ok_r = np.zeros(R, bool)
        ok_r[reps[cnt >= min_repo]] = True
        k2 = keep & ok_r[r]
        deg = np.bincount(a[k2], minlength=A)
        k2 &= (deg >= min_user)[a]
        if k2.sum() == keep.sum():
            return keep
        keep = k2


def _users_in_windows(g: _Graph, P, st, dt, need, restrict=None):
    ei, pos = _gather(g.r_ptr, P)
    act, ts = g.r_actor[ei], g.r_ts[ei]
    s = st[pos]
    inw = (ts >= s) & (ts < s + dt)
    if restrict is not None:
        inw &= restrict[act]
    hits = np.bincount(act[inw], minlength=g.A)
    return np.flatnonzero(hits >= max(need, 1) - EPS)


def _peel(g: _Graph, U, P, p: LockstepParams):
    """Shrink (U, P) until every repo and every account satisfies its condition."""
    while len(U) and len(P):
        inU = np.zeros(g.A, bool)
        inU[U] = True
        ei, pos = _gather(g.r_ptr, P)
        act, ts, rp = g.r_actor[ei], g.r_ts[ei], P[pos]
        sel = inU[act]
        reps, cnt, st = best_windows(rp[sel], ts[sel], p.dt)
        ok = cnt >= p.rho * len(U) - EPS
        P2, st2 = reps[ok], st[ok]
        if len(P2) == 0:
            break
        U2 = _users_in_windows(g, P2, st2, p.dt, p.rho * len(P2) if p.user_side else 1, restrict=inU)
        if len(U2) == len(U) and len(P2) == len(P):
            return U, P2, st2
        U, P = U2, P2
    e = np.array([], dtype=np.int64)
    return e, e, e


def _search(g: _Graph, seed: int, seed_start: int, p: LockstepParams):
    lo, hi = g.r_ptr[seed], g.r_ptr[seed + 1]
    ts = g.r_ts[lo:hi]
    U = np.unique(g.r_actor[lo:hi][(ts >= seed_start) & (ts < seed_start + p.dt)])
    P = np.array([seed])
    for _ in range(p.max_iter):
        ei, _pos = _gather(g.a_ptr, U)
        reps, cnt, st = best_windows(g.a_repo[ei], g.a_ts[ei], p.dt)
        ok = cnt >= p.rho * len(U) - EPS
        P_new, st_new = reps[ok], st[ok]
        if len(P_new) == 0:
            return None
        U_new = _users_in_windows(g, P_new, st_new, p.dt, p.rho * len(P_new) if p.user_side else 1)
        if len(U_new) == 0:
            return None
        done = np.array_equal(U_new, U) and np.array_equal(P_new, P)
        U, P = U_new, P_new
        if done:
            break
    U, P, st = _peel(g, U, P, p)
    if len(U) >= p.n and len(P) >= p.m:
        return U, P, st
    return None


# --------------------------------------------------------------------------- public API
def detect_lockstep(stars: pd.DataFrame, params: LockstepParams) -> tuple[pd.DataFrame, list[dict], dict]:
    """stars: DataFrame(actor_id, repo_id, ts). Returns (flagged edges, group summaries, stats)."""
    stats = {"input_edges": int(len(stars))}
    empty = stars.iloc[0:0][["actor_id", "repo_id", "ts"]]
    if stars.empty:
        return empty, [], stats
    a, a_ids = pd.factorize(stars.actor_id)
    r, r_ids = pd.factorize(stars.repo_id)
    t0 = stars.ts.min()
    t = ((stars.ts - t0).dt.total_seconds()).to_numpy().astype(np.int64)
    row = np.arange(len(stars))

    keep = _prune(a, r, t, len(a_ids), len(r_ids), params)
    stats["edges_after_pruning"] = int(keep.sum())
    if not keep.any():
        stats.update(groups=0, flagged_edges=0, seeds_tried=0)
        return empty, [], stats
    a2, a_map = pd.factorize(a[keep])
    r2, r_map = pd.factorize(r[keep])
    t2, row2 = t[keep], row[keep]
    stats["accounts_after_pruning"], stats["repos_after_pruning"] = len(a_map), len(r_map)
    g = _Graph(a2, r2, t2, row2, len(a_map), len(r_map))

    reps, cnt, starts = best_windows(r2, t2, params.dt)
    order = np.argsort(-cnt, kind="stable")[: params.max_seeds]
    covered = np.zeros(len(r_map), bool)
    groups, flagged_rows, tried = [], [], 0
    for i in order:
        s = reps[i]
        if covered[s]:
            continue
        tried += 1
        res = _search(g, s, starts[i], params)
        if res is None:
            continue
        U, P, st = res
        overlap = covered[P].mean()
        covered[P] = True
        inU = np.zeros(g.A, bool)
        inU[U] = True
        ei, pos = _gather(g.r_ptr, P)
        ts, act = g.r_ts[ei], g.r_actor[ei]
        inw = inU[act] & (ts >= st[pos]) & (ts < st[pos] + params.dt)
        flagged_rows.append(g.r_row[ei][inw])
        per_repo = np.bincount(pos[inw], minlength=len(P))
        new_repos = set(r_ids[r_map[P]].tolist())
        if overlap >= 0.5 and groups:
            # Same campaign re-found from an uncovered seed: merge into the most overlapping group.
            best = max(groups, key=lambda gr: len(new_repos & set(gr["repo_ids"])))
            best["account_ids"] = sorted(set(best["account_ids"]) | set(a_ids[a_map[U]].tolist()))
            best["repo_ids"] = sorted(set(best["repo_ids"]) | new_repos)
            best["n_accounts"], best["n_repos"] = len(best["account_ids"]), len(best["repo_ids"])
            best["merged_searches"] = best.get("merged_searches", 1) + 1
            continue
        groups.append({
            "group_id": len(groups),
            "n_accounts": int(len(U)), "n_repos": int(len(P)),
            "min_repo_share": round(float(per_repo.min() / len(U)), 3),
            "median_repo_share": round(float(np.median(per_repo) / len(U)), 3),
            "first_window": str(t0 + pd.Timedelta(seconds=int(st.min()))),
            "last_window": str(t0 + pd.Timedelta(seconds=int(st.max()))),
            "account_ids": a_ids[a_map[U]].tolist(),
            "repo_ids": r_ids[r_map[P]].tolist(),
        })
    rows = np.unique(np.concatenate(flagged_rows)) if flagged_rows else np.array([], dtype=np.int64)
    flagged = stars.iloc[rows][["actor_id", "repo_id", "ts"]].reset_index(drop=True)
    stats.update(groups=len(groups), seeds_tried=tried, flagged_edges=int(len(flagged)))
    return flagged, groups, stats


def is_lockstep(stars: pd.DataFrame, accounts, repos, params: LockstepParams) -> bool:
    """Check the formal definition for a given (U, P), choosing each repo's densest window."""
    sub = stars[stars.actor_id.isin(accounts) & stars.repo_id.isin(repos)]
    if sub.empty:
        return False
    a, a_ids = pd.factorize(sub.actor_id)
    r, r_ids = pd.factorize(sub.repo_id)
    t = ((sub.ts - sub.ts.min()).dt.total_seconds()).to_numpy().astype(np.int64)
    g = _Graph(a, r, t, np.arange(len(sub)), len(a_ids), len(r_ids))
    U0, P0 = np.arange(len(a_ids)), np.arange(len(r_ids))
    if len(U0) != len(set(accounts)) or len(P0) != len(set(repos)):
        return False  # some given account/repo has no star inside the pair set
    U, P, _ = _peel(g, U0, P0, params)
    return len(U) == len(U0) and len(P) == len(P0) and len(U) >= params.n and len(P) >= params.m
