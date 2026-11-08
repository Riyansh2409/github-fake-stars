import pandas as pd

from conftest import edges, ts
from fakestars.detection.low_activity import low_activity_actors, low_activity_signal


def _profile(rows):
    return pd.DataFrame(rows, columns=["actor_id", "n_events", "n_watch"])


def _small(rows):
    return pd.DataFrame(rows, columns=["event_id", "actor_id", "repo_id", "type", "created_at"])


def test_account_rule_pass_and_fail_cases():
    stars = edges([
        (1, 10, 1.2),             # only a star                         -> pass
        (2, 10, 1.2),             # star + fork same repo same day      -> pass
        (3, 10, 1.2),             # star + fork next day                -> fail
        (4, 10, 1.2), (4, 11, 2), # two starred repos                   -> fail
        (5, 10, 1.2),             # star + 2 other events               -> fail
        (6, 10, 1.2),             # star + push to another repo         -> fail
    ])
    prof = _profile([(1, 1, 1), (2, 2, 1), (3, 2, 1), (4, 2, 2), (5, 3, 1), (6, 2, 1)])
    small = _small([
        ("e2", 2, 10, "ForkEvent", ts(1.3)),
        ("e3", 3, 10, "ForkEvent", ts(2.3)),
        ("e5a", 5, 10, "ForkEvent", ts(1.3)), ("e5b", 5, 10, "IssuesEvent", ts(1.4)),
        ("e6", 6, 99, "PushEvent", ts(1.3)),
    ])
    got = set(low_activity_actors(stars, prof, small, max_other_events=1))
    assert got == {1, 2}


def test_unverifiable_account_is_not_flagged():
    stars = edges([(7, 10, 1.0)])
    prof = _profile([(7, 2, 1)])            # one extra event, but it is missing from small_events
    assert len(low_activity_actors(stars, prof, _small([]), 1)) == 0


def test_repository_star_cutoff():
    rows = [(a, 10, 1.0) for a in range(50)] + [(a, 11, 1.0) for a in range(100, 149)]
    stars = edges(rows)
    prof = _profile([(a, 1, 1) for a in stars.actor_id.unique()])
    flagged, info = low_activity_signal(stars, prof, _small([]), 1, repo_min_stars=50)
    assert set(flagged.repo_id) == {10}       # 50 >= 50 passes, 49 fails
    assert info["low_activity_accounts"] == 99
    assert len(flagged) == 50
