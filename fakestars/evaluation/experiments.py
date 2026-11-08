"""Evaluation plan (proposal Section 6): known-campaign recall, deletion vs. baselines,
behavioural profiling, component ablation, threshold sensitivity, and (synthetic only)
ground-truth precision/recall."""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from ..config import results_dir, with_overrides
from ..detection.copycatch import LockstepParams, detect_lockstep
from ..detection.filtering import filter_campaigns
from ..detection.low_activity import low_activity_actors, low_activity_signal
from ..pipeline import union_edges
from ..utils import log, manifest, peak_rss_mb, write_json
from .baselines import matched_repos, random_actors, random_repos, repo_features
from .deletion import cap, compare, deletion_rate, make_checker
from .known_campaigns import KnownCampaign, load_reference
from .profiling import actor_features, compare_profiles

ORGANIC_REPO = {"organic", "organic_viral", "organic_community"}
ORGANIC_ACTOR = {"organic", "organic_oneoff"}


class Context:
    """Everything shared by evaluation runs: data, reference sets, checker, fixed baselines."""

    def __init__(self, cfg: dict, data: dict, reference_flagged_repos):
        self.cfg, self.data = cfg, data
        ev = cfg["evaluation"]
        self.seed = ev["seed"]
        ref = load_reference(ev["reference_dir"])
        self.known = KnownCampaign(data, ref) if ref else None
        self.checker = make_checker(cfg)
        self.feat = repo_features(data["stars"])
        # Random baseline is fixed once (excluding the default run's flagged repos) so every
        # experiment is compared against the same reference sample.
        self.exclude = set(reference_flagged_repos)
        self._baseline = None
        ref_dir = Path(ev["reference_dir"])
        self.gt_repos = self.gt_actors = None
        if (ref_dir / "ground_truth_repos.parquet").exists():
            self.gt_repos = pd.read_parquet(ref_dir / "ground_truth_repos.parquet").set_index("repo_id").label
            self.gt_actors = pd.read_parquet(ref_dir / "ground_truth_actors.parquet").set_index("actor_id").label

    def baseline_rate(self, size: int):
        if self._baseline is None:
            ids = random_repos(self.feat, self.exclude, size, self.seed)
            self._baseline = deletion_rate(self.checker, "repo", ids)
        return self._baseline

    def ground_truth(self, repos, participants) -> dict:
        if self.gt_repos is None:
            return {}
        stars = self.data["stars"]
        pos_r = set(self.gt_repos[~self.gt_repos.isin(ORGANIC_REPO)].index) & set(stars.repo_id)
        pos_a = set(self.gt_actors[~self.gt_actors.isin(ORGANIC_ACTOR)].index) & set(stars.actor_id)
        fr = set(repos)
        fa = set(participants)
        return {"gt_repo_precision": len(fr & pos_r) / len(fr) if fr else None,
                "gt_repo_recall": len(fr & pos_r) / len(pos_r) if pos_r else None,
                "gt_account_precision": len(fa & pos_a) / len(fa) if fa else None,
                "gt_account_recall": len(fa & pos_a) / len(pos_a) if pos_a else None}

    def metrics(self, low: pd.DataFrame, lock: pd.DataFrame, check_deletion: bool = True) -> dict:
        fc = self.cfg["filtering"]
        union = union_edges(low, lock)
        repos, actors = filter_campaigns(self.data["stars"], union, fc["spike_min_stars"],
                                         fc["spike_min_share"], fc["alltime_min_share"])
        flagged_part = actors[actors.flagged_participant].actor_id if len(actors) else pd.Series([], dtype="int64")
        m = {"flagged_stars": len(union), "flagged_repos_pre_filter": union.repo_id.nunique(),
             "campaign_repos": len(repos), "campaign_participants": actors.actor_id.nunique() if len(actors) else 0,
             "flagged_participants": flagged_part.nunique()}
        if self.known:
            pre = self.known.recall(union.repo_id, union.actor_id)
            post = self.known.recall(repos.repo_id, actors.actor_id if len(actors) else [])
            m.update({f"known_{k}_pre": v for k, v in pre.items()})
            m.update({f"known_{k}": v for k, v in post.items()})
        if check_deletion and len(repos):
            k = self.cfg["evaluation"]["max_repo_checks"]
            r = deletion_rate(self.checker, "repo", cap(repos.repo_id, k, self.seed))
            b = self.baseline_rate(k)
            m.update(deleted_rate_flagged=r["rate"], deleted_rate_random=b["rate"],
                     deletion_diff=r["rate"] - b["rate"])
        m.update(self.ground_truth(repos.repo_id, flagged_part))
        return m



def evaluate(cfg: dict, data: dict, det: dict) -> dict:
    out = results_dir(cfg)
    ev = cfg["evaluation"]
    seed = ev["seed"]
    stars, prof = data["stars"], data["actor_profile"]
    union = union_edges(det["low"], det["lock"])
    ctx = Context(cfg, data, union.repo_id.unique())
    report: dict = {"run": cfg["run_name"]}
    t0 = time.perf_counter()

    # 1. Known-campaign recall
    if ctx.known:
        report["known_campaign"] = {
            **ctx.known.coverage(),
            "before_filtering": ctx.known.recall(union.repo_id, union.actor_id),
            "after_filtering": ctx.known.recall(det["repos"].repo_id, det["actors"].actor_id)}
    else:
        report["known_campaign"] = "reference files not found"

    # 2. Deletion rates: flagged vs random vs matched (repos), flagged vs random (accounts)
    kr, ka = ev["max_repo_checks"], ev["max_actor_checks"]
    flagged = cap(det["repos"].repo_id, kr, seed)
    rows = {"campaign_repos": deletion_rate(ctx.checker, "repo", flagged),
            "random_baseline": ctx.baseline_rate(kr),
            "matched_baseline": deletion_rate(ctx.checker, "repo",
                                              matched_repos(ctx.feat, flagged, ctx.exclude, seed))}
    del_repos = compare(rows)
    del_repos.to_csv(out / "deletion_repos.csv")
    fl_acc = det["actors"][det["actors"].flagged_participant].actor_id.unique()
    rows_a = {"flagged_participants": deletion_rate(ctx.checker, "actor", cap(fl_acc, ka, seed)),
              "random_baseline": deletion_rate(ctx.checker, "actor",
                                               random_actors(stars, union.actor_id.unique(), ka, seed))}
    del_acc = compare(rows_a)
    del_acc.to_csv(out / "deletion_accounts.csv")
    report["deletion"] = {"repos": rows, "accounts": rows_a}

    # 3. Behavioural profiling
    ns = ev["profile_sample"]
    f_ids = cap(fl_acc, ns, seed)
    b_ids = random_actors(stars, union.actor_id.unique(), max(len(f_ids), 1), seed)
    prof_tbl = compare_profiles(prof, stars, f_ids, b_ids)
    prof_tbl.to_csv(out / "profiling.csv", index=False)
    feats = pd.concat([actor_features(prof, stars, f_ids).assign(group="flagged"),
                       actor_features(prof, stars, b_ids).assign(group="random")]).reset_index(drop=True)
    feats.to_parquet(out / "profiling_features.parquet", index=False)  # no identifiers
    report["profiling"] = {"n_flagged": len(f_ids), "n_baseline": len(b_ids),
                           "table": prof_tbl.to_dict(orient="records")}

    # 4. Component ablation
    abl = []
    for name, low, lock in [("low_activity_only", det["low"], None), ("lockstep_only", None, det["lock"]),
                            ("combined", det["low"], det["lock"])]:
        abl.append({"variant": name, **ctx.metrics(low, lock)})
    abl = pd.DataFrame(abl)
    abl.to_csv(out / "ablation.csv", index=False)
    report["ablation"] = abl.to_dict(orient="records")

    # Synthetic only: ground-truth check of the implementation
    gt = ctx.ground_truth(det["repos"].repo_id, fl_acc)
    if gt:
        lab = ctx.gt_repos.reindex(det["repos"].repo_id).fillna("organic").value_counts().to_dict()
        all_lab = ctx.gt_repos[ctx.gt_repos.index.isin(stars.repo_id)]
        report["ground_truth"] = {**gt, "retained_by_label": lab,
                                  "planted_by_label": all_lab[~all_lab.isin(["organic"])].value_counts().to_dict()}

    report["runtime_s"] = round(time.perf_counter() - t0, 2)
    report["peak_memory_mb"] = peak_rss_mb()
    write_json(out / "evaluation.json", report)
    log.info("evaluation written to %s", out)
    return report


def sensitivity(cfg: dict, data: dict, det: dict) -> pd.DataFrame:
    out = results_dir(cfg)
    sc = cfg["sensitivity"]
    union = union_edges(det["low"], det["lock"])
    ctx = Context(cfg, data, union.repo_id.unique())
    la_actors = low_activity_actors(data["stars"], data["actor_profile"], data["small_events"],
                                    cfg["low_activity"]["max_other_events"])
    low_cache, lock_cache = {}, {}
    alias = {"star_cutoff": "low_activity.repo_min_stars", "n": "lockstep.n", "m": "lockstep.m",
             "rho": "lockstep.rho", "delta_t_days": "lockstep.delta_t_days"}

    def run(overrides: dict) -> dict:
        c = with_overrides(cfg, {alias[k]: v for k, v in overrides.items()})
        lk = c["low_activity"]["repo_min_stars"]
        if lk not in low_cache:
            t = time.perf_counter()
            low_cache[lk] = (low_activity_signal(data["stars"], data["actor_profile"], data["small_events"],
                                                 repo_min_stars=lk, actors=la_actors)[0], time.perf_counter() - t)
        p = LockstepParams.from_cfg(c["lockstep"])
        key = (p.n, p.m, p.rho, p.delta_t_days)
        if key not in lock_cache:
            t = time.perf_counter()
            e, g, _ = detect_lockstep(data["stars"], p)
            lock_cache[key] = (e, len(g), time.perf_counter() - t)
        (low, t_low), (lock, n_groups, t_lock) = low_cache[lk], lock_cache[key]
        m = ctx.metrics(low, lock, check_deletion=sc.get("check_deletion", True))
        return {"lockstep_groups": n_groups, **m,
                "runtime_low_s": round(t_low, 3), "runtime_lockstep_s": round(t_lock, 3)}

    defaults = {"star_cutoff": cfg["low_activity"]["repo_min_stars"], **{k: cfg["lockstep"][k] for k in
                ["n", "m", "rho", "delta_t_days"]}}
    rows = [{"experiment": "default", "param": "-", "value": "-", **defaults, **run({})}]
    for param, values in sc["one_at_a_time"].items():
        for v in values:
            if v == defaults[param]:
                continue
            log.info("sensitivity %s=%s", param, v)
            rows.append({"experiment": "one_at_a_time", "param": param, "value": v,
                         **{**defaults, param: v}, **run({param: v})})
    for combo in sc.get("combined", []):
        ov = {k: v for k, v in combo.items() if k != "name"}
        log.info("sensitivity combined %s", combo.get("name"))
        rows.append({"experiment": "combined", "param": combo.get("name", "combo"), "value": "-",
                     **{**defaults, **ov}, **run(ov)})
    df = pd.DataFrame(rows)
    df.to_csv(out / "sensitivity.csv", index=False)
    write_json(out / "sensitivity_manifest.json", {**manifest(cfg), "peak_memory_mb": peak_rss_mb()})
    log.info("sensitivity: %d configurations -> %s", len(df), out / "sensitivity.csv")
    return df
