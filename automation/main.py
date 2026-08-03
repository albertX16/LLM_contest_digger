"""自动化因子挖掘闭环 —— 命令行入口。

用法:
    python automation/main.py --smoke             # 合成数据冒烟（不联网、不烧 API）
    python automation/main.py --rounds 3          # 本地 GA 跑 3 轮
    python automation/main.py --rounds 3 --llm on # 双 agent 用 DeepSeek 参与
    python automation/main.py --rounds 2 --real   # 用本地 bigquant SDK 取真实数据
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.agents.llm_client import LLMClient, load_config
from automation.evaluate.barra import (
    build_local_classic_exposures,
    load_barra_exposures,
    synthetic_exposures,
)
from automation.evaluate.refset import build_default_refset, load_refset_directory
from automation.loop.run_round import RoundRunner
from automation.panel.fetch import fetch_raw_30m, daily_forward_return

log = logging.getLogger("automation.main")


def _start_heartbeat(stop_interval_s: float = 120.0) -> threading.Event:
    """心跳线程：Planner/评分阶段可能长时间静默，用周期日志证明进程存活。

    解决外部 Terminal 里"进程卡住 vs 正常等待"难以区分的问题；
    对正在运行的进程不生效，只影响后续启动。
    """
    stop_event = threading.Event()

    def beat() -> None:
        while not stop_event.wait(stop_interval_s):
            log.info("heartbeat: 进程存活，等待当前阶段（Planner/GA/评分）输出")

    thread = threading.Thread(target=beat, name="research-heartbeat", daemon=True)
    thread.start()
    return stop_event


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="自动化因子挖掘闭环")
    p.add_argument("--smoke", action="store_true", help="合成数据冒烟测试（推荐先跑）")
    p.add_argument("--rounds", type=int, default=1, help="要跑的轮数")
    p.add_argument("--llm", choices=["on", "off"], default="on",
                   help="是否启用 DeepSeek 双 agent（默认 on；off 是显式 GA-only 模式）")
    p.add_argument("--real", action="store_true",
                   help="用本地 bigquant SDK 取真实数据（默认合成数据）")
    p.add_argument("--platform", choices=["on", "off"], default="off",
                   help="是否将幸存 notebook 上传 AIStudio（默认 off；永不自动最终提交）")
    p.add_argument("--preflight", action="store_true",
                   help="只做 DeepSeek 网络/鉴权自检后退出（不启动研究）")
    p.add_argument("--config", default="automation/configs/default.yaml")
    p.add_argument("--run-dir", default=None, help="覆盖配置里的 run_dir")
    p.add_argument("--population", type=int, default=None, help="覆盖 GA population_size")
    p.add_argument("--generations", type=int, default=None, help="覆盖 GA generations")
    p.add_argument("--candidates", type=int, default=None,
                   help="覆盖每轮进入完整评分的候选上限")
    return p


def _load_config(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _synthetic_data(seed: int = 42) -> dict[str, pd.DataFrame]:
    """构造含三档盘口的 30m 合成数据（28 列匹配真实 schema）。"""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", periods=120)
    instruments = [f"{i:06d}.SZ" for i in range(40)]
    intraday_times = ("10:00", "11:00", "14:00", "15:00")
    rows = [
        (pd.Timestamp(f"{d.date()} {clock}"), inst)
        for d in dates for clock in intraday_times for inst in instruments
    ]
    df = pd.DataFrame(rows, columns=["date", "instrument"])
    df["close"] = 100 + rng.standard_normal(len(df)).cumsum() % 30
    df["open"] = df["close"] * (1 + rng.standard_normal(len(df)) * 0.005)
    df["high"] = df[["close", "open"]].max(axis=1) * 1.002
    df["low"] = df[["close", "open"]].min(axis=1) * 0.998
    df["volume"] = rng.integers(1000, 50000, len(df)).astype(float)
    df["amount"] = (df["close"] * df["volume"]).astype(float)
    df["deal_number"] = rng.integers(1, 20, len(df))
    df["adjust_factor"] = 1.0 + rng.standard_normal(len(df)) * 0.001
    for level in (1, 2, 3):
        df[f"bid_price{level}"] = df["close"] * (1 - 0.001 * level + rng.standard_normal(len(df)) * 0.002)
        df[f"ask_price{level}"] = df["close"] * (1 + 0.001 * level + rng.standard_normal(len(df)) * 0.002)
        df[f"bid_volume{level}"] = (df["volume"] * (0.5 / level)).astype(float)
        df[f"ask_volume{level}"] = (df["volume"] * (0.4 / level)).astype(float)
    ret = daily_forward_return(df)
    return {"df": df, "ret": ret}


def _real_data(config: dict) -> dict[str, pd.DataFrame]:
    start, end = config["panel"]["start"], config["panel"]["end"]
    freq = str(config["panel"].get("bar_freq", "30m")).lower()
    if freq in ("30m", "30min"):
        raw = fetch_raw_30m(start, end, config["panel"]["cache_dir"],
                            config["panel"]["source_table"])
        raw["date"] = pd.to_datetime(raw["date"])
        return {"df": raw, "ret": daily_forward_return(raw)}
    if freq in ("1m", "1min"):
        return _real_data_1m_daily(config)
    raise ValueError(f"panel.bar_freq 不支持: {freq}（支持 30m / 1m）")


def _real_data_1m_daily(config: dict) -> dict[str, pd.DataFrame]:
    """2024 1m 模式：确保季度缓存齐全，再把 1m 数据聚合成日频特征面板。

    内存安全：原始 1m 全年数据从不整体载入；build_daily_features 逐季度
    处理并释放，GA 只接触约 24 万行的日频特征面板。
    """
    from automation.panel.daily_features import (
        build_daily_features,
        load_daily_features,
    )
    from automation.panel.fetch_1m import ensure_1m_cache

    panel_cfg = config["panel"]
    start, end = panel_cfg["start"], panel_cfg["end"]
    cache_dir = panel_cfg["cache_dir"]
    feature_path = panel_cfg.get(
        "feature_panel", "data_cache/dai_download/daily_features_2024_1m.parquet")
    # 季度缓存齐全性（缺失季度在此下载，可断点续传）。
    ensure_1m_cache(start, end, cache_dir, panel_cfg["source_table"])
    if Path(feature_path).exists():
        panel = load_daily_features(feature_path)
    else:
        panel = build_daily_features(
            start, end, cache_dir, feature_path, panel_cfg["source_table"])
    return {"df": panel, "ret": daily_forward_return(panel)}


def _make_client(config: dict, llm_on: bool) -> LLMClient | None:
    if not llm_on:
        return None
    return load_config(config)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = _load_config(args.config)
    if args.run_dir:
        config["loop"]["run_dir"] = args.run_dir
    if args.population is not None:
        if args.population < 4:
            raise ValueError("--population 必须 >= 4")
        config["search"]["population_size"] = args.population
    if args.generations is not None:
        if args.generations < 1:
            raise ValueError("--generations 必须 >= 1")
        config["search"]["generations"] = args.generations
    if args.candidates is not None:
        if args.candidates < 1:
            raise ValueError("--candidates 必须 >= 1")
        config["search"]["candidates_per_round"] = args.candidates
    platform_config = config.setdefault("loop", {}).setdefault("platform", {})
    platform_config["auto_upload"] = args.platform == "on"
    # 官方评分/最终提交依赖 AIStudio 页面工作流，命令行不会冒充或点击它。
    platform_config["auto_evaluate"] = False
    if args.smoke:
        config["search"].update({
            "population_size": 12,
            "generations": 3,
            "candidates_per_round": 5,
        })
        config["loop"]["run_dir"] = args.run_dir or "automation/runs_smoke"
        config["evaluate"]["exposure_mode"] = "smoke_fixture"
        config["search"].pop("platform_feedback_file", None)
    # 合成数据只属于显式 smoke；正常运行始终要求真实数据。
    data = _synthetic_data() if args.smoke else _real_data(config)
    if data["df"].empty:
        log.error("数据为空")
        return 2
    client = _make_client(config, args.llm == "on" and not args.smoke)
    if client is not None:
        # 启动前自检网络与 key：沙箱断网/空 content 问题在加载数据前就暴露，
        # 并给出明确的操作提示（外部 Terminal / 网络放行），而不是研究中途失败。
        preflight = client.preflight()
        log.info("DeepSeek 自检通过: %s", preflight["model"])
        if args.preflight:
            log.info("preflight-only 模式：自检通过，退出。")
            return 0
    elif args.preflight:
        log.error("--preflight 需要 --llm on")
        return 2
    refset = build_default_refset(data["df"])
    factorlib = config.get("evaluate", {}).get("factorlib")
    if factorlib:
        refset.update(load_refset_directory(factorlib))
    if not refset:
        raise RuntimeError("RefSet 为空；B-proxy 无法执行拥挤度检查")
    if args.smoke:
        exposures = synthetic_exposures(data["df"])
    else:
        exposure_mode = config["evaluate"].get("exposure_mode")
        if exposure_mode == "local_classic":
            exposures = build_local_classic_exposures(data["df"])
        elif exposure_mode == "official_file":
            exposures = load_barra_exposures(
                config["evaluate"]["exposures_file"],
                config["panel"]["start"], config["panel"]["end"],
            )
        else:
            raise ValueError(
                "evaluate.exposure_mode 必须是 local_classic 或 official_file"
            )
    log.info("数据 %d 行，%d 个标的，RefSet %d 个基线", len(data["df"]),
             data["df"]["instrument"].nunique(), len(refset))
    log.info("风险正交方法=%s，exposures=%d",
             "smoke_fixture" if args.smoke else config["evaluate"]["exposure_mode"],
             len(exposures))
    runner = RoundRunner(config, client, data=data, refset=refset,
                         exposures=exposures)
    start_round = runner.last_completed_round + 1
    stop_heartbeat = _start_heartbeat()
    try:
        for round_no in range(start_round, start_round + args.rounds):
            result = runner.run(round_no)
            log.info("round %d: %d 候选 / %d 保留 (%.1fs)",
                     round_no, result["n_candidates"], result["n_kept"],
                     result["wall_seconds"])
    finally:
        stop_heartbeat.set()
    ledger = Path(config["loop"]["run_dir"]) / "ledger.jsonl"
    n = sum(1 for _ in ledger.open()) if ledger.exists() else 0
    log.info("总 ledger: %d 条 -> %s", n, ledger)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
