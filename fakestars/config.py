"""YAML config loading with `extends:` inheritance and dotted-key overrides."""
from __future__ import annotations

import copy
from pathlib import Path

import pandas as pd
import yaml


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_config(path: str | Path) -> dict:
    path = Path(path)
    cfg = yaml.safe_load(path.read_text()) or {}
    parent = cfg.pop("extends", None)
    if parent:
        cfg = _merge(load_config(path.parent / parent), cfg)
    cfg["_config_path"] = str(path)
    return cfg


def with_overrides(cfg: dict, overrides: dict) -> dict:
    """overrides: {"lockstep.n": 25, ...}"""
    out = copy.deepcopy(cfg)
    for key, val in overrides.items():
        node = out
        parts = key.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = val
    return out


def window(cfg: dict) -> tuple[pd.Timestamp, pd.Timestamp]:
    """[start, end_exclusive) of the analysis window, naive UTC."""
    start = pd.Timestamp(cfg["data"]["start"])
    end_excl = pd.Timestamp(cfg["data"]["end"]) + pd.Timedelta(days=1)
    return start, end_excl


def results_dir(cfg: dict) -> Path:
    d = Path(cfg["output"]["results_dir"]) / cfg["run_name"]
    d.mkdir(parents=True, exist_ok=True)
    return d
