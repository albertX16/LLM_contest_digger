"""质量门控：确认窗口 t 值门控 + 同轮多样性门控。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from automation.evaluate.barra import synthetic_exposures
from automation.evaluate.refset import build_default_refset
from automation.loop.run_round import RoundRunner
from automation.search.genome import Genome
from automation.search.map_elites import MapElitesArchive


def make_daily_panel(days: int = 120, instruments: int = 20, seed: int = 3):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-02", periods=days)
    rows = [(d, i) for d in dates for i in range(1, instruments + 1)]
    panel = pd.DataFrame(rows, columns=["date", "instrument"])
    panel["open"] = 10 + rng.standard_normal(len(panel)).cumsum() % 20
    panel["close"] = panel["open"] * (1 + rng.standard_normal(len(panel)) * 0.01)
    panel["high"] = panel[["open", "close"]].max(axis=1) * 1.01
    panel["low"] = panel[["open", "close"]].min(axis=1) * 0.99
    panel["volume"] = rng.integers(1000, 50000, len(panel)).astype("float32")
    panel["amount"] = panel["close"] * panel["volume"]
    panel["deal_number"] = rng.integers(1, 100, len(panel)).astype("int32")
    panel["adjust_factor"] = 1.0
    for lv in (1, 2, 3):
        panel[f"bid_price{lv}"] = panel["close"] * (1 - 0.001 * lv)
        panel[f"ask_price{lv}"] = panel["close"] * (1 + 0.001 * lv)
        panel[f"bid_volume{lv}"] = (panel["volume"] / lv).astype("float32")
        panel[f"ask_volume{lv}"] = (panel["volume"] / (lv + 1)).astype("float32")
        panel[f"bid_num_orders{lv}"] = rng.integers(1, 30, len(panel)).astype("int32")
        panel[f"ask_num_orders{lv}"] = rng.integers(1, 30, len(panel)).astype("int32")
    return panel


def make_ret(panel: pd.DataFrame) -> pd.DataFrame:
    daily = (panel.sort_values(["instrument", "date"])
             .groupby(["date", "instrument"], sort=False)["close"]
             .last().reset_index())
    daily["ret_fwd"] = (
        daily.groupby("instrument")["close"].shift(-1) / daily["close"] - 1)
    return daily[["date", "instrument", "ret_fwd"]]


def make_runner(panel: pd.DataFrame, config_overrides: dict | None = None) -> RoundRunner:
    config = {
        "loop": {"run_dir": tempfile.mkdtemp(prefix="gate_"),
                 "platform": {"auto_upload": False}},
        "evaluate": {
            "exposure_mode": "smoke_fixture",
            "confirm_split": "2024-07-01",
            "confirm_t_min": 1.5,
            "same_round_corr_max": 0.6,
        },
        "search": {},
        "llm": {"memory": {"planner": "x", "summarizer": "y"}},
        "panel": {"start": "2024-01-01", "end": "2024-12-31"},
    }
    if config_overrides:
        for section, values in config_overrides.items():
            config.setdefault(section, {}).update(values)
    return RoundRunner(
        config, None,
        data={"df": panel, "ret": make_ret(panel)},
        refset=build_default_refset(panel),
        exposures=synthetic_exposures(panel),
    )


def test_confirm_window_gate_rejects_h1_only_signal() -> None:
    panel = make_daily_panel(days=240)
    # 只在搜索段（前 60 天）有信号；确认段无信号
    cutoff = panel["date"] < pd.Timestamp("2024-04-01")
    rng = np.random.default_rng(11)
    panel["signal"] = rng.random(len(panel))  # 确认段纯噪声
    panel.loc[cutoff, "signal"] = panel.loc[cutoff].groupby(
        "date")["close"].rank(pct=True)
    runner = make_runner(panel)
    qv = {"passed": True, "preprocessing": {"neutralized": True}}
    long_panel = panel[["date", "instrument", "signal"]].rename(
        columns={"signal": "factor"})
    runner._apply_confirm_window_gate(qv, long_panel)
    assert qv["passed"] is False
    assert qv["reject_reason"] == "confirm_window_gate_failed"


def test_confirm_window_gate_passes_persistent_signal() -> None:
    panel = make_daily_panel(days=240)
    panel["signal"] = panel.groupby("date")["close"].rank(pct=True)
    runner = make_runner(panel)
    qv = {"passed": True, "preprocessing": {"neutralized": True}}
    long_panel = panel[["date", "instrument", "signal"]].rename(
        columns={"signal": "factor"})
    runner._apply_confirm_window_gate(qv, long_panel)
    assert qv["passed"] is True
    assert abs(qv["confirm_window_t"]) >= 1.5


def _genome(field: str) -> Genome:
    return Genome.from_dict({
        "combine": "rank",
        "blocks": [{"op": "raw", "inputs": [field], "params": {}, "sign": "+"}],
    })


def test_same_round_diversity_skips_correlated_family_member() -> None:
    panel = make_daily_panel(days=60)
    runner = make_runner(panel)
    genome_close = _genome("close")
    genome_volume = _genome("volume")
    for genome in (genome_close, genome_volume):
        runner._genomes[genome.fingerprint()] = genome
    archive1 = MapElitesArchive(n_bins=4)
    archive1.add(genome_close.fingerprint(),
                 {"rank_ic_ir": 0.1, "max_corr_refset": 0.2, "complexity": 1},
                 10.0, payload={"genome": genome_close.to_dict()})
    archive2 = MapElitesArchive(n_bins=4)
    # 机制 2 的最优与机制 1 完全同质（相同 raw close），次优是 volume。
    archive2.add(genome_close.fingerprint(),
                 {"rank_ic_ir": 0.1, "max_corr_refset": 0.2, "complexity": 1},
                 9.0, payload={"genome": genome_close.to_dict()})
    archive2.add(genome_volume.fingerprint(),
                 {"rank_ic_ir": 0.05, "max_corr_refset": 0.3, "complexity": 1},
                 8.0, payload={"genome": genome_volume.to_dict()})
    family_runs = [
        {"slot": 1, "template": {"research_track": "exploit", "hypothesis": "h1"},
         "results": [(genome_close, 10.0)], "archive": archive1},
        {"slot": 2, "template": {"research_track": "explore", "hypothesis": "h2"},
         "results": [(genome_close, 9.0), (genome_volume, 8.0)], "archive": archive2},
    ]
    selected = runner._select_family_candidates(family_runs, candidate_limit=2)
    ids = [genome.fingerprint() for genome, _, _ in selected]
    assert genome_close.fingerprint() in ids
    assert genome_volume.fingerprint() in ids
    assert ids.count(genome_close.fingerprint()) == 1
