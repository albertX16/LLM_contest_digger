"""Build and load the local crowding reference set.

An empty RefSet makes the B-proxy degenerate into an A-score screen. These
baselines are conventional families a new factor should demonstrate distance
from before platform spend; they are not submission candidates.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def _wide(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    panel = frame[["date", "instrument", name]].copy()
    panel[name] = panel.groupby("date")[name].rank(pct=True)
    return panel.pivot(index="date", columns="instrument", values=name).sort_index()


def build_default_refset(bar_frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    frame = bar_frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["date"])
    frame["date"] = frame["timestamp"].dt.normalize()
    frame = frame.sort_values(["instrument", "timestamp"], kind="mergesort")
    daily = frame.groupby(["date", "instrument"], sort=False).agg(
        close=("close", "last"), volume=("volume", "sum"),
        amount=("amount", "sum"), deal_number=("deal_number", "sum"),
        bid_volume1=("bid_volume1", "last"), ask_volume1=("ask_volume1", "last"),
        bid_price1=("bid_price1", "last"), ask_price1=("ask_price1", "last"),
    ).reset_index().sort_values(["instrument", "date"], kind="mergesort")
    by_instrument = daily.groupby("instrument", sort=False)
    daily["momentum_1d"] = by_instrument["close"].pct_change(fill_method=None)
    daily["reversal_5d"] = -by_instrument["close"].pct_change(5, fill_method=None)
    daily["volatility_20d"] = by_instrument["momentum_1d"].transform(
        lambda values: values.rolling(20, min_periods=5).std())
    mid = (daily["ask_price1"] + daily["bid_price1"]) / 2
    daily["spread"] = (daily["ask_price1"] - daily["bid_price1"]) / mid.replace(0, np.nan)
    daily["order_book_imbalance"] = (
        (daily["bid_volume1"] - daily["ask_volume1"])
        / (daily["bid_volume1"] + daily["ask_volume1"]).replace(0, np.nan)
    )
    names = ("momentum_1d", "reversal_5d", "volatility_20d", "volume",
             "amount", "deal_number", "spread", "order_book_imbalance")
    return {name: _wide(daily, name) for name in names}


def load_refset_directory(path: str | Path) -> dict[str, pd.DataFrame]:
    directory = Path(path)
    if not directory.exists():
        return {}
    out: dict[str, pd.DataFrame] = {}
    for file in sorted(directory.iterdir()):
        if file.suffix not in (".parquet", ".csv"):
            continue
        frame = pd.read_parquet(file) if file.suffix == ".parquet" else pd.read_csv(file)
        value_columns = [column for column in frame.columns
                         if column not in ("date", "instrument")]
        for column in value_columns:
            long = frame[["date", "instrument", column]].copy()
            long["date"] = pd.to_datetime(long["date"]).dt.normalize()
            out[f"{file.stem}:{column}"] = long.pivot(
                index="date", columns="instrument", values=column).sort_index()
    return out
