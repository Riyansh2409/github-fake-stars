"""Signal 1 (proposal Section 3.1): low-activity accounts.

Account rule: within the window the account starred exactly one repository and has at most
`max_other_events` other events, all of which involve that repository on the same UTC day as
the star (e.g. a fork).
Repository rule: the signal is applied only to repositories that received at least
`repo_min_stars` stars from such accounts (star cutoff, default 50).
"""
from __future__ import annotations

import pandas as pd


def low_activity_actors(stars: pd.DataFrame, profile: pd.DataFrame, small_events: pd.DataFrame,
                        max_other_events: int = 1) -> pd.Index:
    g = stars.groupby("actor_id").agg(n_repos=("repo_id", "nunique"), repo_id=("repo_id", "first"),
                                      ts=("ts", "min"))
    cand = g[g.n_repos == 1]
    prof = profile.set_index("actor_id")
    n_other = (prof["n_events"] - prof["n_watch"]).reindex(cand.index).fillna(0)
    cand = cand[n_other <= max_other_events]
    n_other = n_other.loc[cand.index]

    no_other = cand.index[n_other.values == 0]
    need = cand[n_other.values > 0]
    if len(need) == 0:
        return pd.Index(no_other, name="actor_id")
    ev = small_events[small_events.actor_id.isin(need.index)].merge(
        need[["repo_id", "ts"]].rename(columns={"repo_id": "star_repo", "ts": "star_ts"}),
        left_on="actor_id", right_index=True)
    if ev.empty:  # extra events not available -> cannot verify -> not flagged
        return pd.Index(no_other, name="actor_id")
    ev["created_at"] = pd.to_datetime(ev["created_at"])
    ev["ok"] = (ev.repo_id == ev.star_repo) & (ev.created_at.dt.floor("D") == ev.star_ts.dt.floor("D"))
    ok = ev.groupby("actor_id")["ok"].all()
    # Accounts whose extra events are missing from small_events cannot be verified -> not flagged.
    passed = need.index.intersection(ok[ok].index)
    return pd.Index(no_other.append(passed), name="actor_id")


def low_activity_signal(stars: pd.DataFrame, profile: pd.DataFrame, small_events: pd.DataFrame,
                        max_other_events: int = 1, repo_min_stars: int = 50,
                        actors: pd.Index | None = None) -> tuple[pd.DataFrame, dict]:
    """Returns flagged star edges (actor_id, repo_id, ts) and summary counts.

    `actors` lets callers reuse a precomputed low-activity account set (sensitivity runs).
    """
    la = actors if actors is not None else low_activity_actors(stars, profile, small_events, max_other_events)
    s = stars[stars.actor_id.isin(la)]
    cnt = s.groupby("repo_id").size()
    repos = cnt.index[cnt >= repo_min_stars]
    flagged = s[s.repo_id.isin(repos)][["actor_id", "repo_id", "ts"]].reset_index(drop=True)
    return flagged, {"low_activity_accounts": int(len(la)), "repos_over_cutoff": int(len(repos)),
                     "flagged_stars": int(len(flagged))}
