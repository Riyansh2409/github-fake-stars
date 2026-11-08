"""Small synthetic end-to-end run: generate -> build -> detect -> evaluate."""
from pathlib import Path

from fakestars.config import load_config, with_overrides
from fakestars.data.build import build, load_tables
from fakestars.data.synthetic import generate
from fakestars.evaluation.experiments import evaluate
from fakestars.pipeline import run_detection

ROOT = Path(__file__).resolve().parents[1]


def test_synthetic_pipeline(tmp_path):
    cfg = load_config(ROOT / "config" / "synthetic.yaml")
    cfg = with_overrides(cfg, {
        "run_name": "e2e", "output.results_dir": str(tmp_path / "results"),
        "data.raw_dir": str(tmp_path / "raw"), "data.processed_db": str(tmp_path / "p.duckdb"),
        "evaluation.reference_dir": str(tmp_path / "ref"),
        "evaluation.oracle_path": str(tmp_path / "ref" / "deletion_oracle.parquet"),
        "synthetic.n_users": 4000, "synthetic.n_repos": 5000, "synthetic.n_oneoff": 1000,
    })
    generate(cfg)
    build(cfg)
    data = load_tables(cfg)
    res = run_detection(cfg, data)
    assert res["summary"]["lockstep"]["groups"] >= 3
    assert res["summary"]["after_filtering"]["campaign_repos"] > 0
    rep = evaluate(cfg, data, {k: res[k] for k in ["low", "lock", "repos", "actors", "groups", "summary"]})
    assert rep["ground_truth"]["gt_repo_precision"] > 0.8
    assert rep["known_campaign"]["after_filtering"]["repo_recall"] > 0.8
    d = rep["deletion"]["repos"]
    assert d["campaign_repos"]["rate"] > d["random_baseline"]["rate"]
