from conftest import edges
from fakestars.detection.filtering import filter_campaigns


def _repo(repo, n_flag, n_org, flag_day=10, org_days=(0, 80), actor0=0):
    fl = [(actor0 + i, repo, flag_day + i * 0.01) for i in range(n_flag)]
    lo, hi = org_days
    org = [(actor0 + 10_000 + i, repo, lo + (hi - lo) * i / max(n_org, 1)) for i in range(n_org)]
    return fl, org


def test_spike_month_and_alltime_share():
    rows, flagged = [], []
    cases = {
        1: (80, 20),     # spike (80 > 50, 80/~87 > 50%) and share 80% -> kept
        2: (40, 5),      # only 40 flagged in a month (not > 50)        -> dropped
        3: (60, 2000),   # spike fails: 60 / (60 + ~25 that month) ok? total share 3% < 10% -> dropped
        4: (51, 0),      # 51 > 50, 100% -> kept
    }
    for repo, (nf, no) in cases.items():
        f, o = _repo(repo, nf, no, actor0=repo * 100_000)
        rows += f + o
        flagged += f
    stars, fl = edges(rows), edges(flagged)
    repos, part = filter_campaigns(stars, fl, 50, 0.5, 0.10)
    assert set(repos.repo_id) == {1, 4}
    assert set(part.repo_id) == {1, 4}
    assert part.flagged_participant.sum() == 80 + 51


def test_monthly_share_must_exceed_half():
    f, o = _repo(5, 60, 100, flag_day=10, org_days=(0, 25))  # 60 flagged vs 100 organic in January
    repos, _ = filter_campaigns(edges(f + o), edges(f), 50, 0.5, 0.10)
    assert repos.empty
