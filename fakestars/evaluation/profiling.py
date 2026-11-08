"""Check 3: behavioural profiling of flagged accounts vs. a random sample of stargazers."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu

from ..data.schema import PROFILE_GROUPS


def actor_features(profile: pd.DataFrame, stars: pd.DataFrame, ids) -> pd.DataFrame:
    p = profile[profile.actor_id.isin(ids)].set_index("actor_id")
    f = pd.DataFrame(index=p.index)
    f["active_days"] = (p.last_ts - p.first_ts).dt.total_seconds() / 86400
    f["n_events"] = p.n_events
    f["n_starred_repos"] = stars[stars.actor_id.isin(ids)].groupby("actor_id").size().reindex(p.index).fillna(0)
    f["star_share"] = p.n_watch / p.n_events  # concentration of activity on starring
    for c in PROFILE_GROUPS:
        f[f"share_{c[2:]}"] = p[c] / p.n_events
    return f


def compare_profiles(profile, stars, flagged_ids, baseline_ids) -> pd.DataFrame:
    a = actor_features(profile, stars, flagged_ids)
    b = actor_features(profile, stars, baseline_ids)
    rows = []
    for col in a.columns:
        x, y = a[col].dropna(), b[col].dropna()
        p = mannwhitneyu(x, y).pvalue if len(x) and len(y) else np.nan
        rows.append({"feature": col, "flagged_median": x.median(), "baseline_median": y.median(),
                     "flagged_mean": x.mean(), "baseline_mean": y.mean(), "mannwhitney_p": p})
    out = pd.DataFrame(rows)
    out.attrs["n_flagged"], out.attrs["n_baseline"] = len(a), len(b)
    return out
