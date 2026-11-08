"""Figures and a Markdown report built from the aggregate result files of a run."""
from __future__ import annotations

import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from .config import results_dir
from .utils import log, read_json

PARAM_LABEL = {"star_cutoff": "star cutoff", "n": "n (min accounts)", "m": "m (min repos)",
               "rho": "ρ (min share)", "delta_t_days": "Δt (days)"}
C1, C2, C3 = "#2a6fdb", "#e4572e", "#7a7a7a"


def _fmt(v, nd=3):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "–"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def _table(df: pd.DataFrame, cols=None) -> str:
    cols = cols or list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(_fmt(r[c]) for c in cols) + " |")
    return "\n".join(lines)


def _plot_sensitivity(sens: pd.DataFrame, out):
    params = [p for p in PARAM_LABEL if p in set(sens.param)]
    if not params:
        return None
    recall_col = next((c for c in ["gt_repo_recall", "known_repo_recall"] if c in sens and sens[c].notna().any()), None)
    fig, axes = plt.subplots(1, len(params), figsize=(3.2 * len(params), 3.1), sharey=False)
    axes = [axes] if len(params) == 1 else axes
    base = sens[sens.experiment == "default"].iloc[0]
    for ax, p in zip(axes, params):
        sub = pd.concat([sens[sens.param == p], base.to_frame().T]).copy()
        sub["x"] = pd.to_numeric(sub[p])
        sub = sub.sort_values("x")
        ax.plot(sub.x, sub.campaign_repos.astype(float), "o-", color=C1, label="campaign repos")
        ax.axvline(float(base[p]), color=C3, ls=":", lw=1)
        ax.set_xlabel(PARAM_LABEL[p])
        ax.set_ylabel("campaign repos", color=C1)
        if recall_col:
            ax2 = ax.twinx()
            ax2.plot(sub.x, sub[recall_col].astype(float), "s--", color=C2)
            ax2.set_ylim(0, 1.05)
            ax2.set_ylabel(recall_col.replace("_", " "), color=C2)
    fig.suptitle("Threshold sensitivity (one parameter varied at a time; dotted = default)", fontsize=10)
    fig.tight_layout()
    path = out / "fig_sensitivity.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path.name


def _plot_deletion(ev: dict, out):
    rows = ev["deletion"]["repos"]
    names = list(rows)
    rates = [rows[n]["rate"] for n in names]
    lo = [rows[n]["rate"] - rows[n]["ci95"][0] for n in names]
    hi = [rows[n]["ci95"][1] - rows[n]["rate"] for n in names]
    fig, ax = plt.subplots(figsize=(5, 3))
    ax.bar(names, rates, yerr=[lo, hi], color=[C2, C3, C1], capsize=4)
    for i, n in enumerate(names):
        ax.text(i, 0.02, f"n={rows[n]['n_resolved']}", ha="center", color="white", fontsize=8)
    ax.set_ylim(0, 1)
    ax.set_ylabel("deleted / unavailable")
    ax.set_title("Repository deletion rate (95% Wilson CI)", fontsize=10)
    fig.tight_layout()
    fig.savefig(out / "fig_deletion.png", dpi=150)
    plt.close(fig)
    return "fig_deletion.png"


def _plot_profiles(out):
    p = out / "profiling_features.parquet"
    if not p.exists():
        return None
    f = pd.read_parquet(p)
    cols = [("active_days", "active span (days)"), ("n_events", "events (log)"), ("star_share", "share of events = star")]
    fig, axes = plt.subplots(1, 3, figsize=(9, 3))
    for ax, (c, lab) in zip(axes, cols):
        data = [f[f.group == g][c].dropna() for g in ["flagged", "random"]]
        ax.boxplot(data, tick_labels=["flagged", "random"], showfliers=False)
        if c == "n_events":
            ax.set_yscale("log")
        ax.set_title(lab, fontsize=9)
    fig.suptitle("Account behaviour: flagged participants vs random stargazers", fontsize=10)
    fig.tight_layout()
    fig.savefig(out / "fig_profiles.png", dpi=150)
    plt.close(fig)
    return "fig_profiles.png"


def _plot_ablation(abl: pd.DataFrame, out):
    fig, ax = plt.subplots(figsize=(5, 3))
    ax.bar(abl.variant, abl.campaign_repos, color=[C3, C1, C2])
    ax.set_ylabel("campaign repos (after filtering)")
    ax.set_title("Component ablation", fontsize=10)
    fig.tight_layout()
    fig.savefig(out / "fig_ablation.png", dpi=150)
    plt.close(fig)
    return "fig_ablation.png"


def make_report(cfg: dict) -> str:
    out = results_dir(cfg)
    q = read_json(out / "data_quality.json")
    det = read_json(out / "detection_summary.json")
    ev = read_json(out / "evaluation.json") if (out / "evaluation.json").exists() else None
    sens = pd.read_csv(out / "sensitivity.csv") if (out / "sensitivity.csv").exists() else None
    md = [f"# Results: `{cfg['run_name']}`", "",
          f"Window {cfg['data']['start']} → {cfg['data']['end']} · source `{q.get('mode')}` · "
          f"thresholds n={cfg['lockstep']['n']}, m={cfg['lockstep']['m']}, ρ={cfg['lockstep']['rho']}, "
          f"Δt={cfg['lockstep']['delta_t_days']}d, star cutoff={cfg['low_activity']['repo_min_stars']}", "",
          "All figures below are aggregates. Flags are *suspected coordination*, not confirmed fraud.", "",
          "## 1. Data quality", "",
          _table(pd.DataFrame([{"step": k, "count": v} for k, v in q.items()
                               if isinstance(v, (int, float)) and k != "raw_files"])), ""]
    b, a = det["before_filtering"], det["after_filtering"]
    md += ["## 2. Detection", "",
           _table(pd.DataFrame([
               {"stage": "low-activity signal", "stars": b["flagged_stars_low"], "repos": det["low_activity"]["repos_over_cutoff"], "accounts": det["low_activity"]["low_activity_accounts"]},
               {"stage": "lockstep signal (CopyCatch)", "stars": b["flagged_stars_lockstep"], "repos": "", "accounts": ""},
               {"stage": "union before filtering", "stars": b["flagged_stars_union"], "repos": b["flagged_repos"], "accounts": b["flagged_accounts"]},
               {"stage": "after filtering (campaigns)", "stars": "", "repos": a["campaign_repos"], "accounts": a["campaign_participants"]},
           ])), "",
           f"Lockstep groups found: **{det['lockstep'].get('groups', 0)}** · edges after pruning: "
           f"{det['lockstep'].get('edges_after_pruning', 0)} of {det['lockstep'].get('input_edges', 0)} · "
           f"runtime (s): " + ", ".join(f"{k[:-2]} {v}" for k, v in det['runtime_s'].items()) + f" · peak memory {det['peak_memory_mb']} MB", ""]
    if ev:
        kc = ev["known_campaign"]
        md += ["## 3. Evaluation", "", "### 3.1 Known-campaign recall (Stargazers Ghost Network)", ""]
        if isinstance(kc, dict):
            md += [f"Coverage: {kc['documented_repos_in_sample']}/{kc['documented_repos']} documented repos appear in the sample; "
                   f"{kc['listed_accounts_in_sample']}/{kc['documented_accounts']} listed accounts; "
                   f"{kc['documented_repo_stargazers_in_sample']} stargazers of documented repos.", "",
                   _table(pd.DataFrame([{"stage": s, **kc[s]} for s in ["before_filtering", "after_filtering"]])), ""]
        else:
            md += [kc, ""]
        md += ["### 3.2 Deletion rate vs baselines (indirect signal)", "",
               _table(pd.read_csv(out / "deletion_repos.csv", index_col=0).reset_index().rename(columns={"index": "group"}),
                      ["group", "n_resolved", "deleted", "rate", "diff_vs_random", "diff_ci95"]), "",
               "Accounts:", "",
               _table(pd.read_csv(out / "deletion_accounts.csv", index_col=0).reset_index().rename(columns={"index": "group"}),
                      ["group", "n_resolved", "deleted", "rate", "diff_vs_random", "diff_ci95"]), "",
               f"![deletion]({_plot_deletion(ev, out)})", "",
               "### 3.3 Behavioural profiling", "",
               f"{ev['profiling']['n_flagged']} flagged participants vs {ev['profiling']['n_baseline']} random stargazers.", "",
               _table(pd.DataFrame(ev["profiling"]["table"]),
                      ["feature", "flagged_median", "baseline_median", "flagged_mean", "baseline_mean", "mannwhitney_p"]), ""]
        pf = _plot_profiles(out)
        if pf:
            md += [f"![profiles]({pf})", ""]
        abl = pd.DataFrame(ev["ablation"])
        cols = [c for c in ["variant", "flagged_stars", "campaign_repos", "flagged_participants", "known_repo_recall",
                            "known_stargazer_account_recall", "deletion_diff", "gt_repo_precision", "gt_repo_recall",
                            "gt_account_precision", "gt_account_recall"] if c in abl]
        md += ["### 3.4 Component ablation", "", _table(abl, cols), "", f"![ablation]({_plot_ablation(abl, out)})", ""]
        if "ground_truth" in ev:
            g = ev["ground_truth"]
            md += ["### 3.5 Synthetic ground truth (implementation check only)", "",
                   f"Repo precision {_fmt(g['gt_repo_precision'])}, recall {_fmt(g['gt_repo_recall'])}; "
                   f"account precision {_fmt(g['gt_account_precision'])}, recall {_fmt(g['gt_account_recall'])}.", "",
                   f"Planted: `{g['planted_by_label']}`  ", f"Retained: `{g['retained_by_label']}`", ""]
    if sens is not None:
        cols = [c for c in ["experiment", "param", "value", "lockstep_groups", "flagged_stars", "campaign_repos",
                            "flagged_participants", "known_repo_recall", "deletion_diff", "gt_repo_precision",
                            "gt_repo_recall", "runtime_lockstep_s"] if c in sens]
        md += ["## 4. Threshold sensitivity", "", _table(sens, cols), ""]
        fs = _plot_sensitivity(sens, out)
        if fs:
            md += [f"![sensitivity]({fs})", ""]
    text = "\n".join(md)
    (out / "REPORT.md").write_text(text, encoding="utf-8")
    log.info("report -> %s", out / "REPORT.md")
    return text
