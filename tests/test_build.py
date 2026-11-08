import duckdb
import pandas as pd

from conftest import ts
from fakestars.data.build import build, load_tables


def _cfg(tmp_path):
    return {"run_name": "t", "data": {"start": "2024-01-01", "end": "2024-01-31", "raw_dir": str(tmp_path / "raw"),
                                      "processed_db": str(tmp_path / "db.duckdb"),
                                      "small_actor_max_other_events": 2},
            "output": {"results_dir": str(tmp_path / "results")}}


def _ev(eid, typ, actor, repo, t):
    return {"event_id": eid, "type": typ, "actor_id": actor, "actor_login": f"u{actor}",
            "repo_id": repo, "repo_name": f"o/r{repo}", "created_at": t}


def test_overlapping_chunks_are_deduplicated_and_bad_rows_removed(tmp_path):
    a = [_ev("1", "WatchEvent", 1, 10, ts(1)), _ev("2", "ForkEvent", 1, 10, ts(1.1)),
         _ev("3", "WatchEvent", 2, 10, ts(5))]
    b = [_ev("3", "WatchEvent", 2, 10, ts(5)),                       # duplicate across chunks
         _ev(None, "WatchEvent", 3, 11, ts(6)), _ev(None, "WatchEvent", 3, 11, ts(6)),  # composite-key dup
         _ev("5", "WatchEvent", None, 11, ts(6)),                    # missing account id
         _ev("6", "WatchEvent", 4, 11, ts(-3)),                      # outside the window
         _ev("7", "MysteryEvent", 4, 11, ts(7)),                     # unexpected type
         _ev("8", "WatchEvent", 2, 10, ts(8))]                       # re-star -> one edge
    raw = tmp_path / "raw" / "events"
    raw.mkdir(parents=True)
    for i, part in enumerate([a, b]):
        df = pd.DataFrame(part)
        df["actor_id"] = df.actor_id.astype("Int64")
        df.to_parquet(raw / f"chunk-{i}.parquet", index=False)
    q = build(_cfg(tmp_path))
    assert q["raw_rows"] == 10
    assert q["removed_missing_ids"] == 1
    assert q["removed_invalid_timestamp"] == 1
    assert q["unexpected_types"] == {"MysteryEvent": 1}
    assert q["removed_duplicates"] == 2
    assert q["unique_star_edges"] == 3          # (1,10) (2,10) (3,11)
    assert q["restar_events_collapsed"] == 1
    t = load_tables(_cfg(tmp_path))
    p = t["actor_profile"].set_index("actor_id")
    assert p.loc[1, "n_events"] == 2 and p.loc[1, "n_fork"] == 1
    assert set(t["small_events"].actor_id) == {1}
