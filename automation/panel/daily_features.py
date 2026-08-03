"""从 1 分钟 bar 构建日频特征面板（内存安全、可审计）。

为什么用日频特征面板：
- 平台评分的输入是日频因子（date/instrument/factor，预测下一交易日收益）；
- 全年 1 分钟数据约 5800 万行，直接让 GA 在 1m 粒度上反复求值既不现实
  （每轮数百次全表扫描）也会造成 ~8GB 内存压力；
- 因此一次性把 1m 数据按季度分块聚合成约 60 个"日内微观结构日频特征"
  （约 24 万行），GA 在这个小面板上搜索，峰值内存只占一个季度。

特征全部由 1m bar 推导，语义固定、可审计；提交 notebook 会用 SQL 在
datasources["bar1m"] 上等价还原。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from automation.panel.fetch_1m import iter_1m_chunks
from automation.panel.fetch import _has_monthly_continuity


# 日频特征清单（顺序即输出列顺序）。字段名与 RAW_FIELDS 合并后供 DSL 校验。
DAILY_FIELDS: tuple[str, ...] = (
    # 基础日线（由 1m 聚合）
    "open", "high", "low", "close", "vwap", "adjust_factor",
    # 成交量/成交额/笔数
    "volume", "amount", "deal_number", "avg_trade_size",
    # 收益形态
    "ret_open_close", "ret_open_vwap", "ret_close_vwap",
    "first30m_ret", "last30m_ret", "am_ret", "pm_ret",
    "close_pos_in_range",
    # 日内分布
    "volume_first30m_share", "volume_last30m_share", "volume_am_share",
    "amount_last30m_share", "deal_number_last30m_share",
    # 日内波动
    "rv_1m", "rv_am", "rv_pm",
    # 收盘时点（最后一根 1m）盘口快照
    "bid_price1", "bid_price2", "bid_price3",
    "ask_price1", "ask_price2", "ask_price3",
    "bid_volume1", "bid_volume2", "bid_volume3",
    "ask_volume1", "ask_volume2", "ask_volume3",
    "bid_num_orders1", "bid_num_orders2", "bid_num_orders3",
    "ask_num_orders1", "ask_num_orders2", "ask_num_orders3",
    # 盘口派生
    "mid_price", "spread", "spread_bps",
    "obi", "oci", "depth1", "depth_all",
    "bid_ask_vol_ratio1", "bid_ask_vol_ratio_all",
    "queue_imbalance_ask", "queue_imbalance_bid",
    "price_gap_ask", "price_gap_bid",
    "microprice", "microprice_premium",
    # 盘口日内动态
    "avg_bid_volume1", "avg_ask_volume1",
    "avg_bid_num_orders1", "avg_ask_num_orders1",
    "avg_obi", "std_obi", "avg_oci", "avg_spread_bps",
)

DAILY_FIELDS_SET = set(DAILY_FIELDS)

_EOD_OB_COLS = tuple(
    f"{side}{kind}{level}"
    for side in ("bid", "ask")
    for kind in ("_price", "_volume", "_num_orders")
    for level in (1, 2, 3)
)


def _safe_div(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator / denominator.replace(0, np.nan)


def build_quarter_features(frame: pd.DataFrame) -> pd.DataFrame:
    """把一个季度的 1m 原始数据聚合成日频特征（长表）。"""
    f = frame.copy()
    f["timestamp"] = pd.to_datetime(f["date"])
    f["d"] = f["timestamp"].dt.normalize()
    f["hhmm"] = f["timestamp"].dt.hour * 100 + f["timestamp"].dt.minute
    f = f.sort_values(["instrument", "timestamp"]).reset_index(drop=True)
    key = ["d", "instrument"]

    daily = f.groupby(key, sort=False).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        amount=("amount", "sum"),
        deal_number=("deal_number", "sum"),
        adjust_factor=("adjust_factor", "last"),
    ).reset_index()
    daily = daily.set_index(["d", "instrument"])
    daily["vwap"] = _safe_div(daily["amount"], daily["volume"])
    daily["avg_trade_size"] = _safe_div(daily["amount"], daily["deal_number"])
    daily["ret_open_close"] = daily["close"] / daily["open"].replace(0, np.nan) - 1
    daily["ret_open_vwap"] = daily["vwap"] / daily["open"].replace(0, np.nan) - 1
    daily["ret_close_vwap"] = daily["close"] / daily["vwap"].replace(0, np.nan) - 1
    daily["close_pos_in_range"] = (daily["close"] - daily["low"]) / (
        daily["high"] - daily["low"]).replace(0, np.nan)

    # 日内时段窗口（A 股 09:31-11:30 / 13:01-15:00；30m 边界为 10:00/11:30/14:31）
    m_first30 = f["hhmm"] <= 1000
    m_am = f["hhmm"] <= 1130
    m_pm = f["hhmm"] >= 1301
    m_last30 = f["hhmm"] >= 1431

    def _window_last(col: str, mask: pd.Series) -> pd.Series:
        return f.loc[mask].groupby(key, sort=False)[col].last()

    def _window_first(col: str, mask: pd.Series) -> pd.Series:
        return f.loc[mask].groupby(key, sort=False)[col].first()

    daily["first30m_ret"] = _window_last("close", m_first30) / daily["open"] - 1
    daily["last30m_ret"] = daily["close"] / _window_first("open", m_last30) - 1
    daily["am_ret"] = _window_last("close", m_am) / daily["open"] - 1
    daily["pm_ret"] = daily["close"] / _window_first("open", m_pm) - 1

    vol_first30 = f.loc[m_first30].groupby(key, sort=False)["volume"].sum()
    vol_last30 = f.loc[m_last30].groupby(key, sort=False)["volume"].sum()
    vol_am = f.loc[m_am].groupby(key, sort=False)["volume"].sum()
    amount_last30 = f.loc[m_last30].groupby(key, sort=False)["amount"].sum()
    dn_last30 = f.loc[m_last30].groupby(key, sort=False)["deal_number"].sum()
    daily["volume_first30m_share"] = vol_first30 / daily["volume"]
    daily["volume_last30m_share"] = vol_last30 / daily["volume"]
    daily["volume_am_share"] = vol_am / daily["volume"]
    daily["amount_last30m_share"] = amount_last30 / daily["amount"]
    daily["deal_number_last30m_share"] = dn_last30 / daily["deal_number"]

    f["ret1m"] = f.groupby("instrument", sort=False)["close"].pct_change(
        fill_method=None)
    sqrt240 = float(np.sqrt(240.0))
    daily["rv_1m"] = f.groupby(key, sort=False)["ret1m"].std(ddof=0) * sqrt240
    daily["rv_am"] = f.loc[m_am].groupby(key, sort=False)["ret1m"].std(ddof=0)
    daily["rv_pm"] = f.loc[m_pm].groupby(key, sort=False)["ret1m"].std(ddof=0)

    # 收盘快照盘口（最后一根 1m bar）
    eod_full = f.sort_values(["instrument", "timestamp"]).groupby(
        key, sort=False).tail(1)
    eod = eod_full.set_index(pd.MultiIndex.from_arrays(
        [eod_full["d"], eod_full["instrument"]],
        names=["d", "instrument"]))[list(_EOD_OB_COLS)]
    for col in _EOD_OB_COLS:
        daily[col] = eod[col]

    # 盘口派生（EOD 快照）
    mid = (daily["bid_price1"] + daily["ask_price1"]) / 2
    daily["mid_price"] = mid
    daily["spread"] = (daily["ask_price1"] - daily["bid_price1"]) / mid.replace(
        0, np.nan)
    daily["spread_bps"] = daily["spread"] * 1e4
    daily["obi"] = _safe_div(daily["bid_volume1"] - daily["ask_volume1"],
                             daily["bid_volume1"] + daily["ask_volume1"])
    daily["oci"] = _safe_div(daily["bid_num_orders1"] - daily["ask_num_orders1"],
                             daily["bid_num_orders1"] + daily["ask_num_orders1"])
    daily["depth1"] = daily["bid_volume1"] + daily["ask_volume1"]
    daily["depth_all"] = (
        daily["bid_volume1"] + daily["bid_volume2"] + daily["bid_volume3"]
        + daily["ask_volume1"] + daily["ask_volume2"] + daily["ask_volume3"])
    daily["bid_ask_vol_ratio1"] = _safe_div(daily["bid_volume1"], daily["ask_volume1"])
    daily["bid_ask_vol_ratio_all"] = _safe_div(
        daily["bid_volume1"] + daily["bid_volume2"] + daily["bid_volume3"],
        daily["ask_volume1"] + daily["ask_volume2"] + daily["ask_volume3"])
    daily["queue_imbalance_ask"] = _safe_div(
        daily["ask_num_orders2"], daily["ask_num_orders1"])
    daily["queue_imbalance_bid"] = _safe_div(
        daily["bid_num_orders2"], daily["bid_num_orders1"])
    daily["price_gap_ask"] = daily["ask_price2"] - daily["ask_price1"]
    daily["price_gap_bid"] = daily["bid_price1"] - daily["bid_price2"]
    daily["microprice"] = _safe_div(
        daily["bid_price1"] * daily["ask_volume1"]
        + daily["ask_price1"] * daily["bid_volume1"],
        daily["bid_volume1"] + daily["ask_volume1"])
    daily["microprice_premium"] = daily["microprice"] / daily["close"].replace(
        0, np.nan) - 1

    # 盘口日内动态
    f["mid_row"] = (f["bid_price1"] + f["ask_price1"]) / 2
    f["spread_row"] = (f["ask_price1"] - f["bid_price1"]) / f["mid_row"].replace(
        0, np.nan)
    f["obi_row"] = _safe_div(f["bid_volume1"] - f["ask_volume1"],
                             f["bid_volume1"] + f["ask_volume1"])
    f["oci_row"] = _safe_div(f["bid_num_orders1"] - f["ask_num_orders1"],
                             f["bid_num_orders1"] + f["ask_num_orders1"])
    dynamics = f.groupby(key, sort=False).agg(
        avg_bid_volume1=("bid_volume1", "mean"),
        avg_ask_volume1=("ask_volume1", "mean"),
        avg_bid_num_orders1=("bid_num_orders1", "mean"),
        avg_ask_num_orders1=("ask_num_orders1", "mean"),
        avg_obi=("obi_row", "mean"),
        std_obi=("obi_row", "std"),
        avg_oci=("oci_row", "mean"),
        avg_spread_bps=("spread_row", "mean"),
    )
    for col in dynamics.columns:
        daily[col] = dynamics[col]

    daily = daily.reset_index().rename(columns={"d": "date"})
    keep = ["date", "instrument", *DAILY_FIELDS]
    daily = daily[[column for column in keep if column in daily.columns]]
    return daily


def _downcast_daily(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    float64_cols = {"amount", "vwap", "avg_trade_size"}
    for col in out.columns:
        if col in ("date", "instrument"):
            continue
        if col not in float64_cols:
            out[col] = pd.to_numeric(out[col], errors="coerce").astype("float32")
    out["instrument"] = pd.to_numeric(
        out["instrument"], errors="coerce").astype("int16")
    return out


def build_daily_features(
    start: str,
    end: str,
    cache_dir: str | Path = "data_cache/dai_download",
    out_path: str | Path = "data_cache/dai_download/daily_features_2024_1m.parquet",
    table: str = "bigalpha_2026_e2e_bar1m",
) -> pd.DataFrame:
    """逐季度把 1m 原始缓存聚合成日频特征面板并落盘。

    每季度处理完立即释放，峰值内存约等于一个季度；输出面板很小
    （约 24 万行 × 60 列），GA 全程只接触这个面板。
    """
    parts: list[pd.DataFrame] = []
    for chunk in iter_1m_chunks(start, end, cache_dir, table=table):
        if len(chunk) == 0:
            del chunk
            continue  # 全假期周（空缓存）不产生日频行
        daily = build_quarter_features(chunk)
        parts.append(daily)
        del chunk, daily
    panel = pd.concat(parts, ignore_index=True)
    panel = panel.drop_duplicates(["date", "instrument"], keep="last")
    panel = panel.sort_values(["date", "instrument"]).reset_index(drop=True)
    span_days = int((pd.Timestamp(end) - pd.Timestamp(start)).days)
    if span_days > 10 and not _has_monthly_continuity(panel, start, end):
        raise ValueError(
            f"日频特征面板月份不连续 {start}..{end}，请先补齐 1m 缓存")
    panel = _downcast_daily(panel)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(out_path, index=False)
    print(f"[daily_features] {len(panel)} 行 x {len(panel.columns)} 列 -> {out_path}")
    return panel


def load_daily_features(
    path: str | Path = "data_cache/dai_download/daily_features_2024_1m.parquet",
) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    missing = sorted(set(DAILY_FIELDS).difference(frame.columns))
    if missing:
        raise ValueError(f"日频特征面板缺少列: {missing}")
    if "date" not in frame.columns or "instrument" not in frame.columns:
        raise ValueError("日频特征面板缺少 date/instrument")
    frame["date"] = pd.to_datetime(frame["date"])
    return frame
