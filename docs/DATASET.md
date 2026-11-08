# Dataset creation

No new labelled dataset is created (buying stars to make labels would fund the activity under
study, proposal Section 1). The study builds an **analysis sample** from public GH Archive events,
plus a **synthetic dataset** with planted ground truth for implementation checks. Both go through
the same preprocessing code.

## 1. Collection

### 1a. GH Archive via BigQuery (main path, `extract-bq`)
- Tables: `githubarchive.day.YYYYMMDD` (public). Window from config, default 2024-01-01 → 2024-03-31.
- Columns: event id, type, actor id/login, repo id/name, created_at. `payload` is never read
  (it is most of the table's size).
- Three queries (`sql/bigquery/`):
  1. `01_star_events.sql` – every `WatchEvent` (a star), run in **31-day chunks overlapping by
     2 days** so no boundary is missed.
  2. `02_actor_profile.sql` – per-stargazer activity counts by event type (all event types),
     deduplicated by event id, used for the low-activity rule and profiling.
  3. `03_small_actor_events.sql` – the non-star events of stargazers with ≤ 2 non-star events
     (the only rows the low-activity rule needs to inspect).
- `--dry-run` reports bytes scanned per query before anything is billed (the pilot cost check);
  `extraction.max_gb_billed` makes BigQuery refuse any query above the cap.

### 1b. Direct GH Archive download (no cloud account, `extract-gha`)
Downloads `https://data.gharchive.org/YYYY-MM-DD-H.json.gz`, keeps the same 7 columns, writes one
parquet per day (resumable). Practical for days–weeks; use 1a for a quarter.

### 1c. Synthetic (`synth`)
`fakestars/data/synthetic.py`, parameters in `config/synthetic.yaml`, fixed seed:
organic users (log-normal activity, Zipf repo popularity), genuine one-off accounts, viral
single-repo bursts, genuine communities starring their org's repos (a legitimate-coordination
trap), seller pools serving many repos (lockstep, incl. one evasive seller below ρ), fresh
single-use accounts (low-activity, incl. campaigns below the 50-star cutoff). Writes ground-truth
labels, a "documented campaign" subset (with entries absent from the sample), and simulated
deletion status.

## 2. Preprocessing (`build`, `fakestars/data/build.py`)
Order of operations, each logged with counts in `results/<run>/data_quality.json`:
1. drop rows missing account id, repository id or type;
2. drop rows with missing timestamps or timestamps outside the window;
3. drop unexpected event types (counted per type);
4. **deduplicate** by event id; rows without an id use the composite key
   (actor, repo, type, timestamp) – this removes duplicates created by overlapping chunks;
5. collapse repeated stars by the same account on the same repository into one edge
   (first star time) → the account–repository graph;
6. build per-account activity profiles and the small-events table.

Final counts reported: raw rows, removed rows by reason, unique star events, unique edges,
unique accounts, unique repositories.

## 3. Annotation
None by hand. Evaluation uses only existing public references and indirect signals:
- Stargazers Ghost Network lists (`data/reference/`, see its README);
- repository/account availability from the GitHub REST API (cached in `deletion_cache.json`);
- random and size/age-matched comparison samples drawn with a fixed seed.

## 4. Pilot finding (documented before looking at detection results)
Checking the Ghost Network reference against GH Archive dates: star activity on the documented
repositories begins in March 2024 and is concentrated in Sep–Nov 2024 (Oct: ~110k, Nov: ~119k star
events). Q1 2024 has ~30. Therefore:
- the main run keeps the proposal's Q1 2024 window (`config/default.yaml`);
- known-campaign recall is measured on a second window, Sep 1 – Nov 30 2024
  (`config/ghost_window.yaml`), with identical thresholds.

## 5. Storage and privacy
Only the 7 columns above are stored. Account/repository identifiers from detections stay in
`results/<run>/detections/` (git-ignored); committed outputs are aggregates.
