# Six Million (Suspected) Fake Stars on GitHub — a scaled reproduction

**Team Alt+F4** — Moksh Jain, Priyansh Ghatliya, Riyansh Jain

Implementation of our research proposal: a scaled-down, reproducible version of the two-signal
fake-star detector of He et al. (ICSE '26) on public GH Archive data —
**(1)** low-activity accounts, **(2)** lockstep groups found with a CopyCatch-style search,
then a **repository filtering stage**, evaluated with known-campaign recall, deletion rates vs.
baselines, behavioural profiling, component ablation, and threshold sensitivity.

> Outputs are *suspected coordination*, not proof of fraud. Committed results are aggregates only.

---

## Quick start (synthetic demo, ~10 seconds, no accounts needed)

```bash
git clone <this-repo-url> && cd github-fake-stars
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m fakestars demo --config config/synthetic.yaml   # generate -> build -> detect -> evaluate -> sensitivity -> report
pytest -q                                                 # 16 tests
```
Open `results/synthetic_demo/REPORT.md` (tables + figures). Python 3.10+.

## Real data (GH Archive)

**Option A — BigQuery (full quarter, as in the proposal).** Needs a Google Cloud project; the free
BigQuery sandbox (1 TiB of queries/month) is enough because only 5–7 small columns are read.

```bash
pip install -r requirements-bigquery.txt
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=<your-project-id>
export GITHUB_TOKEN=<a classic token, no scopes>        # for the deletion check (5000 req/h)

python -m fakestars extract-bq --config config/default.yaml --dry-run   # pilot: bytes/cost per query
python -m fakestars extract-bq --config config/default.yaml             # writes data/raw/
python -m fakestars run        --config config/default.yaml             # build -> ... -> report
```

**Option B — no cloud account.** Downloads hourly GH Archive files for a short window
(default one week, ~15–20 GB download, kept as ~1 GB of parquet):

```bash
python -m fakestars extract-gha --config config/gharchive_pilot.yaml
python -m fakestars run         --config config/gharchive_pilot.yaml
```

**Known-campaign recall window.** The Stargazers Ghost Network is almost absent from Q1 2024
(see *Pilot finding* below), so its recall is measured on Sep–Nov 2024 with the same thresholds:
```bash
python -m fakestars extract-bq --config config/ghost_window.yaml && python -m fakestars run --config config/ghost_window.yaml
```

### Commands
| Command | What it does |
|---|---|
| `synth` | generate the synthetic dataset (planted campaigns + data-quality noise) |
| `extract-bq [--dry-run]` | extract stars / profiles / small events from BigQuery, overlapping chunks |
| `extract-gha` | download hourly GH Archive files (no cloud) |
| `build` | quality checks, dedup, local DuckDB database, `data_quality.json` |
| `detect` | Signal 1 + Signal 2 + filtering, `detection_summary.json` |
| `evaluate` | recall, deletion vs random/matched baselines, profiling, ablation |
| `sensitivity` | one-at-a-time + combined threshold grid, `sensitivity.csv` |
| `report` | figures + `REPORT.md` |
| `run` / `demo` | `build → detect → evaluate → sensitivity → report` / `synth` + `run` |

All thresholds live in `config/*.yaml` (`extends:` inherits from `default.yaml`).
Every run writes `run_manifest.json` (resolved config, package versions, git commit, seed).

---

## Proposal → code

| Proposal section | Implementation |
|---|---|
| 3.1 Low-activity accounts (≤1 extra event on the starred repo, same day; ≥50 per repo) | `fakestars/detection/low_activity.py` |
| 3.2 Lockstep, bipartite graph, n, m, ρ, Δt, CopyCatch | `fakestars/detection/copycatch.py` |
| 3.3 Filtering: spike month (>50 and >50%) + all-time share >10%; participants | `fakestars/detection/filtering.py` |
| Table 1 parameters | `config/default.yaml` |
| 4.1–4.2 GH Archive via BigQuery, needed fields only, overlapping chunks, local DB | `sql/bigquery/*.sql`, `fakestars/data/extract_bigquery.py`, `fakestars/data/build.py` (DuckDB) |
| 5 Data-quality checks, dedup before graph construction, counts per filter | `fakestars/data/build.py` → `data_quality.json` |
| 5 Implementation checks on small synthetic graphs (pass and fail cases) | `tests/` |
| 5 Resource/cost controls: dry-run pilot, byte cap, runtime, peak memory | `extract-bq --dry-run`, `max_gb_billed`, `detection_summary.json` |
| 6.1 Known-campaign recall (repos and accounts separately, coverage reported) | `fakestars/evaluation/known_campaigns.py`, `data/reference/` |
| 6.2 Deletion rates vs random and size/age-matched baselines, with CIs | `fakestars/evaluation/deletion.py`, `baselines.py` |
| 6.3 Behavioural profiling (activity span, event mix, star concentration) | `fakestars/evaluation/profiling.py` |
| 6.4 Component ablation (low only / lockstep only / combined) | `fakestars/evaluation/experiments.py::evaluate` |
| 6.1 Threshold sensitivity (pre-registered ranges in config) | `fakestars/evaluation/experiments.py::sensitivity` |

### How the lockstep search works
After pruning edges that cannot belong to any valid group (each repo needs ≥ ⌈ρn⌉ stars in some
Δt window, each account ≥ ⌈ρm⌉ such repos; iterated to a fixed point), we seed from the largest
uncovered burst and alternate: **repo step** – for every repo the group touched, take its densest
Δt window and keep repos where ≥ ρ|U| of the group starred inside it; **user step** – keep accounts
that starred ≥ ρ|P| of those repos inside their windows. Windows are per repository, so they can
fall in different months (the proposal's X/Y/Z example is a unit test). On convergence the group
is *peeled* (shrink-only) until both conditions hold exactly, and accepted if |U| ≥ n, |P| ≥ m.
The user-side condition follows the original CopyCatch; set `lockstep.user_side: false` to use
only the repository-side condition. Optional chunked runs: `lockstep.chunk_days` with
`chunk_overlap_days ≥ Δt`.

---

## Synthetic demo results (implementation check)

Default thresholds (n=50, m=10, ρ=0.5, Δt=30 d, cutoff 50) on ~300k synthetic events with
planted campaigns. Full tables in `results/synthetic_demo/REPORT.md`.

| | campaign repos | repo precision | repo recall | account precision | account recall |
|---|---|---|---|---|---|
| low-activity only | 25 | 1.00 | 0.23 | 1.00 | 0.70 |
| lockstep only | 67 | 0.85 | 0.53 | 0.90 | 0.17 |
| **combined** | **92** | **0.89** | **0.77** | **0.98** | **0.87** |

- Misses are the planted hard cases: the evasive seller (each order uses 25–45% of its pool, below
  ρ) and low-activity campaigns under the 50-star cutoff. Lowering ρ to 0.3 recovers the evasive
  seller (recall 0.88).
- False positives are the planted *genuine communities* (an org's members starring its repos in
  bursts): lockstep behaviour is not unique to sellers — this is why outputs are "suspected".
- Deletion rate: campaign repos 0.72 vs 0.05 random baseline vs 0.29 matched baseline.
- Profiling: flagged participants have median 1 event and 0 active days vs 9 events and ~15 days
  for random stargazers.

These numbers validate the *code*, not real-world accuracy.

## Pilot finding: choose the window to match the reference campaign
The Ghost Network reference lists (1,414 repos, 374 accounts) have ~30 star events in Q1 2024
and ~230k in Oct–Nov 2024 (checked against GH Archive data published by He et al.). Known-campaign
recall is therefore reported on `config/ghost_window.yaml`; the Q1 2024 run reports the other checks.
Details in `docs/DATASET.md`.

## Repository layout
```
config/            default (Q1 2024), ghost_window, gharchive_pilot, synthetic
sql/bigquery/      extraction queries
fakestars/
  data/            extract_bigquery, download_gharchive, synthetic, build (DuckDB), schema
  detection/       low_activity, copycatch, filtering
  evaluation/      known_campaigns, deletion, baselines, profiling, experiments
  pipeline.py      signal union + filtering, runtime/memory, saving
  report.py        figures + REPORT.md
  cli.py           python -m fakestars <command>
data/reference/    Stargazers Ghost Network lists (+ provenance README)
docs/DATASET.md    collection, preprocessing, annotation, pilot finding
results/           aggregate outputs per run (identifiers are git-ignored)
tests/             unit + end-to-end tests
```

## Limitations and ethics
- Signals are statistical indicators; genuine users and communities can match them (see the
  synthetic false positives). Results are aggregates; we publish no per-account accusations.
- Low activity is judged inside the window only; an account active before/after may look inactive.
- The greedy search does not guarantee finding every group; restricted windows miss campaigns
  outside the sample.
- Deletion is an imperfect proxy (inactivity, policy action, unrelated reasons); associations are
  not causal.
- Public data only, only required fields stored, API rate limits respected, no stars bought.

## References
1. H. He, H. Yang, P. Burckhardt, A. Kapravelos, B. Vasilescu, C. Kästner. *Six Million (Suspected)
   Fake Stars on GitHub.* ICSE '26. Code/data: https://github.com/hehao98/StarScout
2. A. Beutel, W. Xu, V. Guruswami, C. Palow, C. Faloutsos. *CopyCatch.* WWW 2013.
3. GH Archive. https://www.gharchive.org/
4. Check Point Research. *Stargazers Ghost Network*, 2024.
