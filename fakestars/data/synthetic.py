"""Synthetic GH-Archive-like event stream with planted campaigns (known ground truth).

Purpose: implementation checks and a laptop-sized end-to-end demo (proposal Section 5,
"Implementation checks"). It does NOT establish real-world validity.

What is generated
  organic      : users with log-normal activity over a Zipf repository popularity
  one-off      : genuine accounts that star one repo and leave (low-activity false-positive trap)
  viral        : organic bursts on single repos (lockstep false-positive trap)
  sellers      : account pools serving many customer repos in short delivery windows (lockstep)
  low campaigns: fresh single-use accounts bought for one repo (low-activity)
plus injected data-quality problems (duplicates, missing ids, bad timestamps, unknown types)
and overlapping time-chunk files so `build` has to deduplicate across chunks.

Reference files (cfg.evaluation.reference_dir):
  ground_truth_repos.parquet / ground_truth_actors.parquet  labels (synthetic only)
  ghost_network_repos.csv / ghost_network_accounts.csv      "documented campaign" subset
  deletion_oracle.parquet                                   simulated deletion status
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..config import window
from ..utils import log, write_json
from .schema import STAR

DAY = 86400.0
ORG_TYPES = ["PushEvent", STAR, "CreateEvent", "IssueCommentEvent", "PullRequestEvent",
             "IssuesEvent", "ForkEvent", "DeleteEvent", "PullRequestReviewEvent"]
ORG_P = [0.45, 0.15, 0.10, 0.10, 0.07, 0.05, 0.03, 0.03, 0.02]


class _Buf:
    def __init__(self):
        self.parts = []

    def add(self, types, actors, repos, ts):
        n = len(actors)
        types = np.broadcast_to(np.asarray(types, dtype=object), (n,))
        repos = np.broadcast_to(np.asarray(repos, dtype=np.int64), (n,))
        self.parts.append(pd.DataFrame({"type": types, "actor_id": np.asarray(actors, np.int64),
                                        "repo_id": repos, "t": np.asarray(ts, float)}))

    def frame(self):
        return pd.concat(self.parts, ignore_index=True)


def generate(cfg: dict) -> dict:
    sc = cfg["synthetic"]
    rng = np.random.default_rng(sc["seed"])
    start, end_excl = window(cfg)
    T = (end_excl - start).total_seconds()
    buf = _Buf()
    next_actor = [10_000_000]
    next_repo = [50_000_000]

    def new_actors(k):
        ids = np.arange(next_actor[0], next_actor[0] + k)
        next_actor[0] += k
        return ids

    def new_repo():
        next_repo[0] += 1
        return next_repo[0]

    # ---- organic users -------------------------------------------------------------------
    R = sc["n_repos"]
    repo_ids = np.arange(1, R + 1)
    pop = 1.0 / np.arange(1, R + 1) ** sc["zipf"]
    pop /= pop.sum()
    U = sc["n_users"]
    users = np.arange(1, U + 1)
    n_ev = np.clip(rng.lognormal(sc["events_mu"], sc["events_sigma"], U).astype(int), 1, 500)
    actor = np.repeat(users, n_ev)
    E = len(actor)
    types = rng.choice(ORG_TYPES, size=E, p=ORG_P)
    home = rng.choice(repo_ids, size=U, p=pop)
    rand_repo = rng.choice(repo_ids, size=E, p=pop)
    use_home = ~np.isin(types, [STAR, "ForkEvent"]) & (rng.random(E) < 0.8)
    repo = np.where(use_home, home[actor - 1], rand_repo)
    s_u = rng.uniform(0, T, U)
    span = rng.uniform(0.05, 1, U) * (T - s_u)
    ts = s_u[actor - 1] + rng.uniform(0, 1, E) * span[actor - 1]
    buf.parts.append(pd.DataFrame({"type": types, "actor_id": actor, "repo_id": repo, "t": ts}))

    gt_repo = {}   # repo_id -> label
    gt_actor = {}  # actor_id -> label

    # ---- genuine one-off accounts ----------------------------------------------------------
    O = sc["n_oneoff"]
    ids = new_actors(O)
    r = rng.choice(repo_ids, O, p=pop)
    t = rng.uniform(0, T - DAY, O)
    buf.add(STAR, ids, r, t)
    fk = rng.random(O) < 0.15
    buf.add("ForkEvent", ids[fk], r[fk], t[fk] + rng.uniform(0, 600, fk.sum()))
    for a in ids:
        gt_actor[a] = "organic_oneoff"

    # ---- viral organic bursts ---------------------------------------------------------------
    for i in range(sc["viral"]["count"]):
        rid = int(rng.integers(200, 2000))
        fans = rng.choice(users, sc["viral"]["stars"], replace=False)
        t0 = rng.uniform(0, T - sc["viral"]["days"] * DAY)
        buf.add(STAR, fans, rid, t0 + rng.uniform(0, sc["viral"]["days"] * DAY, len(fans)))
        gt_repo[rid] = "organic_viral"

    # ---- genuine communities (an org's members starring its new repos) -------------------------
    # Legitimate coordination: a lockstep false-positive trap that thresholds may not separate.
    for ci, c in enumerate(sc.get("communities", [])):
        members = rng.choice(users, c["members"], replace=False)
        for _ in range(c["repos"]):
            rid = int(next_repo[0] + 1)
            next_repo[0] += 1
            gt_repo[rid] = "organic_community"
            part = rng.choice(members, int(round(rng.uniform(*c["participation"]) * len(members))), replace=False)
            spread = rng.uniform(*c["spread_days"]) * DAY
            t0 = rng.uniform(0, T - spread)
            buf.add(STAR, part, rid, t0 + rng.exponential(spread / 3, len(part)).clip(0, spread))
            k = int(rng.integers(5, 40))
            buf.add("PushEvent", rng.choice(members, k), rid, rng.uniform(0, T, k))

    def owner_and_organic(rid):
        owner = new_actors(1)
        k = int(rng.integers(3, 15))
        buf.add(rng.choice(["PushEvent", "CreateEvent"], k, p=[0.8, 0.2]), np.repeat(owner, k), rid,
                rng.uniform(0, T, k))
        n_org = rng.poisson(sc["campaign_organic_stars"])
        buf.add(STAR, rng.choice(users, n_org, replace=False), rid, rng.uniform(0, T, n_org))

    ghost_repos, ghost_accounts = [], []

    # ---- lockstep sellers --------------------------------------------------------------------
    for si, s in enumerate(sc["sellers"]):
        pool = new_actors(s["pool"])
        for a in pool:
            gt_actor[a] = f"seller_{si}"
        # a little camouflage: a few other events and stars on popular repos
        k = rng.integers(0, 4, len(pool))
        buf.add("CreateEvent", np.repeat(pool, k), rng.choice(repo_ids, k.sum(), p=pop), rng.uniform(0, T, k.sum()))
        c = rng.poisson(1.0, len(pool))
        buf.add(STAR, np.repeat(pool, c), rng.choice(repo_ids[:500], c.sum()), rng.uniform(0, T, c.sum()))
        for _ in range(s["orders"]):
            rid = new_repo()
            gt_repo[rid] = f"seller_{si}"
            owner_and_organic(rid)
            frac = rng.uniform(*s["fraction"])
            members = rng.choice(pool, int(round(frac * len(pool))), replace=False)
            delivery = rng.uniform(*s["delivery_days"]) * DAY
            t0 = rng.uniform(0, T - delivery)
            buf.add(STAR, members, rid, t0 + rng.uniform(0, delivery, len(members)))
            if s.get("ghost"):
                ghost_repos.append(rid)
        if s.get("ghost"):
            ghost_accounts.extend(pool.tolist())

    # ---- low-activity campaigns ----------------------------------------------------------------
    def low_campaign(size, label, lc):
        rid = new_repo()
        gt_repo[rid] = label
        owner_and_organic(rid)
        acc = new_actors(size)
        for a in acc:
            gt_actor[a] = label
        delivery = rng.uniform(*lc.get("delivery_days", [1, 7])) * DAY
        t0 = rng.uniform(0, T - delivery - DAY)
        tt = t0 + rng.uniform(0, delivery, size)
        buf.add(STAR, acc, rid, tt)
        fk = rng.random(size) < lc.get("fork_prob", 0.2)
        buf.add("ForkEvent", acc[fk], rid, tt[fk] + rng.uniform(0, 600, fk.sum()))

    lc = sc["low_campaigns"]
    for _ in range(lc["count"]):
        low_campaign(int(rng.integers(*lc["size"])), "low_activity", lc)
    slc = sc["small_low_campaigns"]
    for _ in range(slc["count"]):
        low_campaign(int(rng.integers(*slc["size"])), "low_activity_small", lc)

    # ---- assemble ------------------------------------------------------------------------------
    df = buf.frame()
    df = df[df.t < T].sort_values("t", kind="stable").reset_index(drop=True)
    df["created_at"] = start + pd.to_timedelta(df.pop("t"), unit="s")
    df["created_at"] = df["created_at"].dt.floor("s")
    df.insert(0, "event_id", (np.arange(len(df)) + 1_000_000_000).astype(str))
    df["actor_login"] = "user" + df.actor_id.astype(str)
    df["repo_name"] = np.where(df.repo_id < 50_000_000,
                               "owner" + (df.repo_id % 5000).astype(str) + "/repo-" + df.repo_id.astype(str),
                               "acct" + (df.repo_id % 997).astype(str) + "/project-" + df.repo_id.astype(str))
    truth_events = len(df)

    # ---- inject data-quality problems ---------------------------------------------------------
    nz = sc["noise"]
    df["event_id"] = df["event_id"].astype(object)
    df["actor_id"] = df["actor_id"].astype("Int64")
    dups = df.sample(frac=nz["duplicate"], random_state=1)
    m = rng.random(len(df))
    df.loc[m < nz["null_actor"], "actor_id"] = pd.NA
    m = rng.random(len(df))
    df.loc[m < nz["null_ts"], "created_at"] = pd.NaT
    m = rng.random(len(df))
    df.loc[m < nz["unknown_type"], "type"] = "UnknownEvent"
    m = rng.random(len(df))
    df.loc[m < nz["null_event_id"], "event_id"] = None
    m = rng.random(len(df))
    df.loc[m < nz["out_of_window"], "created_at"] = start - pd.Timedelta(days=3)
    df = pd.concat([df, dups], ignore_index=True)

    # ---- write overlapping monthly chunk files --------------------------------------------------
    raw = Path(cfg["data"]["raw_dir"]) / "events"
    raw.mkdir(parents=True, exist_ok=True)
    for f in raw.glob("*.parquet"):
        f.unlink()
    ov = pd.Timedelta(days=cfg["extraction"]["overlap_days"])
    months = pd.date_range(start, end_excl, freq="MS")
    edges = list(months) + ([end_excl] if months[-1] != end_excl else [])
    for i in range(len(edges) - 1):
        lo, hi = edges[i] - ov, edges[i + 1] + ov
        sel = (df.created_at >= lo) & (df.created_at < hi)
        if i == 0:
            sel |= df.created_at.isna() | (df.created_at < lo)
        part = df[sel]
        part.to_parquet(raw / f"chunk-{i:02d}.parquet", index=False)

    # ---- reference files ------------------------------------------------------------------------
    ref = Path(cfg["evaluation"]["reference_dir"])
    ref.mkdir(parents=True, exist_ok=True)
    clean = df.dropna(subset=["actor_id"])
    all_repos = pd.Index(clean.repo_id.unique())
    all_actors = pd.Index(clean.actor_id.astype("int64").unique())
    gtr = pd.DataFrame({"repo_id": all_repos})
    gtr["label"] = gtr.repo_id.map(gt_repo).fillna("organic")
    gta = pd.DataFrame({"actor_id": all_actors})
    gta["label"] = gta.actor_id.map(gt_actor).fillna("organic")
    gtr.to_parquet(ref / "ground_truth_repos.parquet", index=False)
    gta.to_parquet(ref / "ground_truth_actors.parquet", index=False)

    names = clean.drop_duplicates("repo_id").set_index("repo_id").repo_name
    gu = sc["ghost_unseen"]
    pd.DataFrame({"repo_name": [names[r] for r in ghost_repos] +
                  [f"ghost-unseen/repo-{i}" for i in range(gu["repos"])]}).to_csv(ref / "ghost_network_repos.csv", index=False)
    pd.DataFrame({"login": [f"user{a}" for a in ghost_accounts] +
                  [f"ghost-unseen-{i}" for i in range(gu["accounts"])]}).to_csv(ref / "ghost_network_accounts.csv", index=False)

    dp = sc["deletion_prob"]
    camp_r = ~gtr.label.isin(["organic", "organic_viral", "organic_community"])
    camp_a = ~gta.label.isin(["organic", "organic_oneoff"])
    orc = pd.concat([
        pd.DataFrame({"kind": "repo", "id": gtr.repo_id,
                      "deleted": rng.random(len(gtr)) < np.where(camp_r, dp["campaign_repo"], dp["organic_repo"])}),
        pd.DataFrame({"kind": "actor", "id": gta.actor_id,
                      "deleted": rng.random(len(gta)) < np.where(camp_a, dp["campaign_actor"], dp["organic_actor"])}),
    ])
    orc.to_parquet(ref / "deletion_oracle.parquet", index=False)

    info = {"events_clean": truth_events, "rows_written_incl_noise": len(df),
            "organic_users": U, "repos": int(len(all_repos)),
            "repo_labels": gtr.label.value_counts().to_dict(),
            "actor_labels": gta.label.value_counts().to_dict(),
            "ghost_repos_listed": len(ghost_repos) + gu["repos"],
            "ghost_accounts_listed": len(ghost_accounts) + gu["accounts"]}
    write_json(ref / "synthetic_info.json", info)
    log.info("synthetic: %d events (+noise -> %d rows) in %s", truth_events, len(df), raw)
    return info
