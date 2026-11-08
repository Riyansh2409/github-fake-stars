"""Check 2: criterion validity via deletion rates (an indirect signal, never proof).

GitHubAPIChecker: GET /repositories/{id} and /user/{id}. 200 = available; 404/410/451 = deleted
or unavailable; anything else = error (excluded from rates). Results are cached on disk so
reruns and sensitivity experiments do not repeat calls. Respects the rate-limit headers.
OracleChecker: simulated deletion status for the synthetic dataset.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from ..utils import diff_ci, log, wilson

API = "https://api.github.com"
_PATH = {"repo": "/repositories/{}", "actor": "/user/{}"}


class OracleChecker:
    def __init__(self, path: str):
        df = pd.read_parquet(path)
        self.lookup = {(k, int(i)): bool(d) for k, i, d in zip(df.kind, df.id, df.deleted)}

    def check(self, kind: str, ids) -> dict:
        return {int(i): self.lookup.get((kind, int(i))) for i in ids}


class GitHubAPIChecker:
    def __init__(self, cache_path: str | None, token_env: str = "GITHUB_TOKEN"):
        self.cache_path = Path(cache_path) if cache_path else None
        self.cache = {"repo": {}, "actor": {}}
        if self.cache_path and self.cache_path.exists():
            self.cache.update(json.loads(self.cache_path.read_text()))
        self.s = requests.Session()
        self.s.headers.update({"Accept": "application/vnd.github+json", "User-Agent": "fakestars-research"})
        tok = os.environ.get(token_env)
        if tok:
            self.s.headers["Authorization"] = f"Bearer {tok}"
        else:
            log.warning("%s not set: unauthenticated GitHub API allows only 60 requests/hour", token_env)

    def _save(self):
        if self.cache_path:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.cache))

    def _one(self, kind: str, i: int) -> str:
        for _ in range(5):
            try:
                r = self.s.get(API + _PATH[kind].format(i), timeout=30)
            except requests.RequestException:
                time.sleep(5)
                continue
            if r.status_code == 200:
                return "alive"
            if r.status_code in (404, 410, 451):
                return "deleted"
            if r.status_code in (403, 429) and r.headers.get("X-RateLimit-Remaining") == "0":
                wait = max(1, int(r.headers.get("X-RateLimit-Reset", time.time() + 60)) - int(time.time()) + 2)
                log.info("rate limited, sleeping %ds", wait)
                time.sleep(wait)
                continue
            return "error"
        return "error"

    def check(self, kind: str, ids) -> dict:
        c = self.cache[kind]
        todo = [int(i) for i in ids if str(int(i)) not in c]
        for n, i in enumerate(todo, 1):
            c[str(i)] = self._one(kind, i)
            if n % 100 == 0:
                log.info("GitHub API: %d/%d %s checks", n, len(todo), kind)
                self._save()
        if todo:
            self._save()
        return {int(i): {"alive": False, "deleted": True}.get(c[str(int(i))]) for i in ids}


def make_checker(cfg: dict):
    ev = cfg["evaluation"]
    if ev["deletion_source"] == "oracle":
        return OracleChecker(ev["oracle_path"])
    return GitHubAPIChecker(ev.get("deletion_cache"), ev.get("github_token_env", "GITHUB_TOKEN"))


def cap(ids, k: int, seed: int) -> list:
    ids = sorted(set(int(i) for i in ids))
    if len(ids) <= k:
        return ids
    return sorted(np.random.default_rng(seed).choice(ids, k, replace=False).tolist())


def deletion_rate(checker, kind: str, ids) -> dict:
    st = checker.check(kind, ids)
    known = [v for v in st.values() if v is not None]
    k, n = int(sum(known)), len(known)
    p, lo, hi = wilson(k, n)
    return {"n_checked": len(st), "n_resolved": n, "deleted": k, "rate": p, "ci95": [lo, hi]}


def compare(rows: dict) -> pd.DataFrame:
    """rows: {group_name: deletion_rate dict}; adds differences against the random baseline."""
    df = pd.DataFrame(rows).T
    if "random_baseline" in rows:
        b = rows["random_baseline"]
        for g, r in rows.items():
            d, lo, hi = diff_ci(r["deleted"], r["n_resolved"], b["deleted"], b["n_resolved"])
            df.loc[g, "diff_vs_random"] = d
            df.loc[g, "diff_ci95"] = f"[{lo:.3f}, {hi:.3f}]"
    return df
