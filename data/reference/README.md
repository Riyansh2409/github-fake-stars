# Reference data: Stargazers Ghost Network

| File | Rows | Content |
|---|---|---|
| `ghost_network_repos.csv` | 1,414 | `repo_name` (owner/name) of repositories documented in the campaign |
| `ghost_network_accounts.csv` | 374 | `login` of accounts documented in the campaign |

**Source.** Check Point Research, *Stargazers Ghost Network* (2024),
https://research.checkpoint.com/2024/stargazers-ghost-network/ — as compiled by He et al. in the
StarScout repository (`scripts/analysis/checkpoint.py`, https://github.com/hehao98/StarScout,
Apache-2.0). We extracted the two lists unchanged; no accounts or repositories were added.

**Use.** Only for measuring recall of known campaign items that appear in our sample
(`fakestars/evaluation/known_campaigns.py`). Listing here does not mean every item is malicious;
the lists are the publisher's indicators, reproduced for research evaluation.

**Time coverage (pilot finding).** In GH Archive, star activity on these repositories starts in
March 2024 and peaks in October–November 2024 (~110k star events per month). Q1 2024 contains
only ~30 such star events, so recall on the Q1 2024 sample is not measurable; use
`config/ghost_window.yaml` (Sep–Nov 2024) for this check. See `docs/DATASET.md`.
