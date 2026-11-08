"""Command line: python -m fakestars <command> --config <yaml>"""
from __future__ import annotations

import argparse
import time

from .config import load_config
from .utils import log, setup_logging


def _data(cfg):
    from .data.build import load_tables
    return load_tables(cfg)


def cmd_synth(cfg, a):
    from .data.synthetic import generate
    generate(cfg)


def cmd_extract_bq(cfg, a):
    from .data.extract_bigquery import extract
    extract(cfg, dry_run=a.dry_run)


def cmd_extract_gha(cfg, a):
    from .data.download_gharchive import download
    download(cfg)


def cmd_build(cfg, a):
    from .data.build import build
    build(cfg)


def cmd_detect(cfg, a):
    from .pipeline import run_detection, save_detection
    save_detection(cfg, run_detection(cfg, _data(cfg)))


def cmd_evaluate(cfg, a):
    from .evaluation.experiments import evaluate
    from .pipeline import load_detection
    evaluate(cfg, _data(cfg), load_detection(cfg))


def cmd_sensitivity(cfg, a):
    from .evaluation.experiments import sensitivity
    from .pipeline import load_detection
    sensitivity(cfg, _data(cfg), load_detection(cfg))


def cmd_report(cfg, a):
    from .report import make_report
    make_report(cfg)


def cmd_run(cfg, a):
    """build -> detect -> evaluate -> sensitivity -> report (raw data must already exist)."""
    for f in (cmd_build, cmd_detect, cmd_evaluate, cmd_sensitivity, cmd_report):
        if f is cmd_sensitivity and a.skip_sensitivity:
            continue
        log.info("== %s", f.__name__[4:])
        f(cfg, a)


def cmd_demo(cfg, a):
    """Synthetic end-to-end demo: synth + run."""
    cmd_synth(cfg, a)
    cmd_run(cfg, a)


COMMANDS = {
    "synth": (cmd_synth, "generate the synthetic dataset"),
    "extract-bq": (cmd_extract_bq, "extract the sample from GH Archive on BigQuery"),
    "extract-gha": (cmd_extract_gha, "download hourly GH Archive files (no cloud account)"),
    "build": (cmd_build, "quality checks + dedup -> local DuckDB"),
    "detect": (cmd_detect, "run both signals + filtering"),
    "evaluate": (cmd_evaluate, "recall, deletion vs baselines, profiling, ablation"),
    "sensitivity": (cmd_sensitivity, "threshold sensitivity grid"),
    "report": (cmd_report, "figures + REPORT.md"),
    "run": (cmd_run, "build, detect, evaluate, sensitivity, report"),
    "demo": (cmd_demo, "synthetic end-to-end demo (synth + run)"),
}


def main(argv=None):
    p = argparse.ArgumentParser(prog="fakestars", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for name, (_, help_) in COMMANDS.items():
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--config", "-c", default="config/default.yaml")
        sp.add_argument("--verbose", "-v", action="store_true")
        if name == "extract-bq":
            sp.add_argument("--dry-run", action="store_true", help="only estimate bytes scanned / cost")
        if name in ("run", "demo"):
            sp.add_argument("--skip-sensitivity", action="store_true")
    a = p.parse_args(argv)
    setup_logging(a.verbose)
    cfg = load_config(a.config)
    t = time.perf_counter()
    COMMANDS[a.command][0](cfg, a)
    log.info("%s finished in %.1f s", a.command, time.perf_counter() - t)
