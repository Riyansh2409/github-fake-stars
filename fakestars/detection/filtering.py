"""Filtering stage (proposal Section 3.3).

A repository with flagged stars is retained only if
  (1) in at least one calendar month it received > spike_min_stars flagged stars AND those
      were > spike_min_share of all its stars that month ("spike month"), and
  (2) flagged stars are > alltime_min_share of all its stars in the analysis window.
Accounts that starred a retained repository during its spike months are potential campaign
participants (flagged_participant marks those that were themselves flagged).
"""
from __future__ import annotations

import pandas as pd


def filter_campaigns(stars: pd.DataFrame, flagged: pd.DataFrame, spike_min_stars: int = 50,
                     spike_min_share: float = 0.5, alltime_min_share: float = 0.10):
    cols = ["repo_id", "total_stars", "flagged_stars", "flagged_share", "spike_months"]
    if flagged.empty:
        return pd.DataFrame(columns=cols), pd.DataFrame(columns=["actor_id", "repo_id", "flagged_participant"])
    fl = flagged[["actor_id", "repo_id"]].drop_duplicates().assign(flag=True)
    s = stars[stars.repo_id.isin(fl.repo_id.unique())][["actor_id", "repo_id", "ts"]]
    s = s.merge(fl, on=["actor_id", "repo_id"], how="left")
    s["flag"] = s["flag"].fillna(False).astype(bool)
    s["month"] = s.ts.dt.to_period("M")

    monthly = s.groupby(["repo_id", "month"]).agg(total=("flag", "size"), flagged=("flag", "sum"))
    monthly["spike"] = (monthly.flagged > spike_min_stars) & (monthly.flagged / monthly.total > spike_min_share)
    alltime = s.groupby("repo_id").agg(total_stars=("flag", "size"), flagged_stars=("flag", "sum"))
    alltime["flagged_share"] = alltime.flagged_stars / alltime.total_stars
    spikes = monthly[monthly.spike].reset_index()
    alltime["spike_months"] = spikes.groupby("repo_id").size().reindex(alltime.index, fill_value=0)
    kept = alltime[(alltime.spike_months > 0) & (alltime.flagged_share > alltime_min_share)].reset_index()

    sp = spikes[spikes.repo_id.isin(kept.repo_id)][["repo_id", "month"]]
    part = s.merge(sp, on=["repo_id", "month"])[["actor_id", "repo_id", "flag"]]
    part = part.rename(columns={"flag": "flagged_participant"}).drop_duplicates(["actor_id", "repo_id"])
    return kept[cols], part.reset_index(drop=True)
