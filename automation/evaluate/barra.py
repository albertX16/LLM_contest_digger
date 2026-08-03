"""Strict loading of the local BARRA style/industry exposure panel."""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd

REPO_EVAL = (
    Path(__file__).resolve().parents[2]
    / "bigalpha2026_main_src/bigalpha2026-main/eval"
)
if str(REPO_EVAL) not in sys.path:
    sys.path.insert(0, str(REPO_EVAL))

from scorer.neutralize import exposures_from_panel


EXPECTED_STYLES = {
    "SIZE", "BETA", "MOMENTUM", "RESVOL", "SIZENL", "BTOP",
    "LIQUIDTY", "EARNYILD", "GROWTH", "LEVERAGE",
}


def load_barra_exposures(
    path: str | Path,
    start: str,
    end: str,
    *,
    min_instruments: int = 30,
) -> dict[str, pd.DataFrame]:
    """Load and validate the official local exposure export; never proxy it.

    The caller gets an exception for a missing file, missing style, insufficient
    cross-section or inadequate date coverage.  A bar-derived approximation must
    not silently take the place of the official exposure panel.
    """
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(
            f"缺少本地 BARRA exposure 文件: {source}。"
            "必须先导出 bigalpha_2026_exposure，系统不会用价格/成交量代理降级替代。"
        )
    if source.suffix == ".parquet":
        panel = pd.read_parquet(source)
    elif source.suffix == ".csv":
        panel = pd.read_csv(source)
    else:
        raise ValueError(f"BARRA exposure 仅支持 parquet/csv: {source}")
    required = {"date", "instrument"} | EXPECTED_STYLES
    missing = sorted(required.difference(panel.columns))
    if missing:
        raise ValueError(f"BARRA exposure 缺列: {missing}")
    panel = panel.copy()
    panel["date"] = pd.to_datetime(panel["date"], errors="raise").dt.normalize()
    panel["instrument"] = panel["instrument"].astype(str)
    if panel.duplicated(["date", "instrument"]).any():
        raise ValueError("BARRA exposure 存在重复 date/instrument")
    if panel["instrument"].nunique() < min_instruments:
        raise ValueError(
            f"BARRA exposure 横截面仅 {panel['instrument'].nunique()} 个标的，"
            f"低于最低要求 {min_instruments}"
        )
    requested_start = pd.Timestamp(start)
    requested_end = pd.Timestamp(end)
    actual_start = panel["date"].min()
    actual_end = panel["date"].max()
    # The official competition universe begins on 2019-06-05.  A small holiday
    # tolerance is accepted; a partial-year cache is not.
    if actual_start > requested_start + pd.Timedelta(days=7):
        raise ValueError(
            f"BARRA exposure 起点 {actual_start.date()} 晚于回测起点 {requested_start.date()}"
        )
    if actual_end < requested_end - pd.Timedelta(days=7):
        raise ValueError(
            f"BARRA exposure 终点 {actual_end.date()} 早于回测终点 {requested_end.date()}"
        )
    panel = panel[(panel["date"] >= requested_start)
                  & (panel["date"] <= requested_end)]
    exposures = exposures_from_panel(panel)
    if not EXPECTED_STYLES.issubset(exposures):
        raise ValueError("BARRA exposure 转宽表后十个经典风格未完整保留")
    return exposures


def synthetic_exposures(bar_frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Explicit test fixture for ``--smoke`` only, never used by a real run."""
    frame = bar_frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["date"])
    frame["date"] = frame["timestamp"].dt.normalize()
    daily = (frame.sort_values(["instrument", "timestamp"])
             .groupby(["date", "instrument"], sort=False)
             .agg(close=("close", "last"), volume=("volume", "sum"),
                  amount=("amount", "sum"))
             .reset_index().sort_values(["instrument", "date"]))
    grouped = daily.groupby("instrument", sort=False)
    ret = grouped["close"].pct_change(fill_method=None)
    daily["SIZE"] = np.log(daily["amount"].clip(lower=1))
    daily["MOMENTUM"] = grouped["close"].pct_change(20, fill_method=None)
    daily["RESVOL"] = ret.groupby(daily["instrument"]).transform(
        lambda values: values.rolling(20, min_periods=5).std())
    daily["LIQUIDTY"] = np.log(daily["volume"].clip(lower=1))
    return {
        name: daily.pivot(index="date", columns="instrument", values=name).sort_index()
        for name in ("SIZE", "MOMENTUM", "RESVOL", "LIQUIDTY")
    }


def build_local_classic_exposures(
    bar_frame: pd.DataFrame,
    *,
    beta_window: int = 60,
    min_periods: int = 20,
) -> dict[str, pd.DataFrame]:
    """Construct explicit bar-derived classic style controls for local research.

    These are not labelled as the organizer's official BARRA exposures.  They
    are deterministic local controls for the major traditional return styles
    that can be identified from the authorized bar fields alone.
    """
    required = {"date", "instrument", "close", "volume", "amount"}
    missing = sorted(required.difference(bar_frame.columns))
    if missing:
        raise ValueError(f"本地经典风格控制缺少 bar 字段: {missing}")
    frame = bar_frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["date"], errors="raise")
    frame["date"] = frame["timestamp"].dt.normalize()
    daily = (frame.sort_values(["instrument", "timestamp"], kind="mergesort")
             .groupby(["date", "instrument"], sort=False)
             .agg(close=("close", "last"), volume=("volume", "sum"),
                  amount=("amount", "sum"))
             .reset_index())
    close = daily.pivot(index="date", columns="instrument", values="close").sort_index()
    volume = daily.pivot(index="date", columns="instrument", values="volume").sort_index()
    amount = daily.pivot(index="date", columns="instrument", values="amount").sort_index()
    returns = close.pct_change(fill_method=None)
    market_return = returns.mean(axis=1)
    market_var = market_return.rolling(beta_window, min_periods=min_periods).var()
    beta = pd.DataFrame(index=returns.index, columns=returns.columns, dtype=float)
    for instrument in returns.columns:
        beta[instrument] = (
            returns[instrument].rolling(beta_window, min_periods=min_periods)
            .cov(market_return) / market_var.replace(0, np.nan)
        )
    size = np.log(amount.rolling(20, min_periods=5).mean().clip(lower=1))
    size_centered = size.sub(size.mean(axis=1), axis=0)
    controls = {
        "LOCAL_SIZE_PROXY": size,
        "LOCAL_BETA_60D": beta,
        "LOCAL_MOMENTUM_20D": close.pct_change(20, fill_method=None),
        "LOCAL_REVERSAL_5D": -close.pct_change(5, fill_method=None),
        "LOCAL_RESVOL_20D": returns.rolling(20, min_periods=5).std(),
        "LOCAL_SIZENL_PROXY": size_centered.pow(3),
        "LOCAL_ILLIQUIDITY_20D": (
            returns.abs() / amount.replace(0, np.nan)
        ).rolling(20, min_periods=5).mean(),
        "LOCAL_PRICE_LEVEL": np.log(close.clip(lower=1e-12)),
        "LOCAL_VOLUME_20D": np.log(
            volume.rolling(20, min_periods=5).mean().clip(lower=1)
        ),
    }
    if any(panel.empty for panel in controls.values()):
        raise ValueError("本地经典风格控制构造为空")
    return controls
