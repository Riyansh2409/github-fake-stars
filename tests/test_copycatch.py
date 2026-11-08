import numpy as np

from conftest import edges, noise, planted_group
from fakestars.detection.copycatch import LockstepParams, best_windows, detect_lockstep, is_lockstep

P = LockstepParams(n=50, m=10, rho=0.5, delta_t_days=30)


def test_best_windows():
    repo = np.array([0, 0, 0, 0, 1, 1])
    t = np.array([0, 10, 20, 100, 5, 500])
    r, c, s = best_windows(repo, t, dt=25)
    assert r.tolist() == [0, 1] and c.tolist() == [3, 1] and s.tolist()[0] == 0


def test_proposal_example_definition():
    """Section 3.2 example: A,B,C x X,Y,Z, n=m=3, rho=2/3, 30-day windows in different months."""
    A, B, C, X, Y, Z = 1, 2, 3, 10, 11, 12
    stars = edges([(A, X, 35), (B, X, 40),      # February
                   (B, Y, 125), (C, Y, 130),    # May
                   (A, Z, 220), (C, Z, 228)])   # August
    p = LockstepParams(n=3, m=3, rho=2 / 3, delta_t_days=30)
    assert is_lockstep(stars, [A, B, C], [X, Y, Z], p)
    # Spread Y's stars 100 days apart: no 30-day window holds 2 of 3 accounts any more.
    bad = edges([(A, X, 35), (B, X, 40), (B, Y, 125), (C, Y, 225), (A, Z, 220), (C, Z, 228)])
    assert not is_lockstep(bad, [A, B, C], [X, Y, Z], p)


def test_planted_group_is_found_among_noise():
    stars = edges(planted_group() + noise())
    flagged, groups, stats = detect_lockstep(stars, P)
    assert len(groups) == 1
    g = groups[0]
    assert g["n_repos"] == 12 and 50 <= g["n_accounts"] <= 60
    assert set(g["repo_ids"]) == set(range(500, 512))
    assert set(flagged.actor_id) <= set(range(1000, 1060))     # no noise accounts flagged


def test_too_few_accounts_is_rejected():
    stars = edges(planted_group(n_acc=40, share=0.9) + noise())   # 40 < n=50
    assert detect_lockstep(stars, P)[1] == []


def test_too_few_repositories_is_rejected():
    stars = edges(planted_group(n_repo=8) + noise())              # 8 < m=10
    assert detect_lockstep(stars, P)[1] == []


def test_share_below_rho_is_rejected():
    stars = edges(planted_group(n_acc=120, share=0.3) + noise())  # each repo: 30% of pool < rho
    assert detect_lockstep(stars, LockstepParams(n=50, m=10, rho=0.5, delta_t_days=30))[1] == []


def test_stars_spread_beyond_window_are_rejected():
    stars = edges(planted_group(spread_days=120) + noise(days=200))  # delivery spread over 4 months
    assert detect_lockstep(stars, P)[1] == []


def test_noise_alone_gives_no_groups():
    assert detect_lockstep(edges(noise(n_stars=20000)), P)[1] == []


def test_two_independent_groups():
    stars = edges(planted_group(seed=1) + planted_group(seed=2, actor0=5000, repo0=800) + noise())
    groups = detect_lockstep(stars, P)[1]
    assert len(groups) == 2
