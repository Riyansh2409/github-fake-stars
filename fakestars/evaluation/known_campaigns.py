"""Check 1: recall on a publicly documented campaign (Stargazers Ghost Network, Check Point 2024).

Reference files in cfg.evaluation.reference_dir:
  ghost_network_repos.csv     column repo_name  (owner/name)
  ghost_network_accounts.csv  column login
Recall is computed only over reference items that appear in our sample; sample coverage is
reported separately. Accounts are evaluated two ways: the listed accounts, and every account
that starred a documented repository inside the sample ("documented-repo stargazers").
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_reference(ref_dir: str | Path) -> dict | None:
    ref_dir = Path(ref_dir)
    rp, ap = ref_dir / "ghost_network_repos.csv", ref_dir / "ghost_network_accounts.csv"
    if not rp.exists():
        return None
    repos = set(pd.read_csv(rp).repo_name.dropna().str.lower())
    accounts = set(pd.read_csv(ap).login.dropna().str.lower()) if ap.exists() else set()
    return {"repos": repos, "accounts": accounts}


class KnownCampaign:
    def __init__(self, data: dict, ref: dict):
        names = data["repo_names"]
        logins = data["actor_logins"]
        stars = data["stars"]
        in_sample = names[names.repo_id.isin(stars.repo_id.unique())]
        hit = in_sample[in_sample.repo_name.str.lower().isin(ref["repos"])]
        self.repo_ids = set(hit.repo_id)
        self.n_ref_repos = len(ref["repos"])
        self.n_ref_repos_in_sample = hit.repo_name.str.lower().nunique()
        acc = logins[logins.login.str.lower().isin(ref["accounts"])]
        self.listed_account_ids = set(acc.actor_id)
        self.n_ref_accounts = len(ref["accounts"])
        self.stargazer_ids = set(stars[stars.repo_id.isin(self.repo_ids)].actor_id)

    def coverage(self) -> dict:
        return {"documented_repos": self.n_ref_repos, "documented_repos_in_sample": self.n_ref_repos_in_sample,
                "repo_coverage": self.n_ref_repos_in_sample / self.n_ref_repos if self.n_ref_repos else None,
                "documented_accounts": self.n_ref_accounts,
                "listed_accounts_in_sample": len(self.listed_account_ids),
                "documented_repo_stargazers_in_sample": len(self.stargazer_ids)}

    @staticmethod
    def _rec(truth: set, found: set):
        return (len(truth & found) / len(truth)) if truth else None

    def recall(self, flagged_repos, flagged_accounts) -> dict:
        fr, fa = set(flagged_repos), set(flagged_accounts)
        return {"repo_recall": self._rec(self.repo_ids, fr),
                "listed_account_recall": self._rec(self.listed_account_ids, fa),
                "stargazer_account_recall": self._rec(self.stargazer_ids, fa)}
