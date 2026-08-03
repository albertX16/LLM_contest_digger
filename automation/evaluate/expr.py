"""Deterministic pandas evaluator for the typed genome DSL."""

from __future__ import annotations

import numpy as np
import pandas as pd

from automation.search.genome import ExpressionBlock, Genome, validate_genome


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator / denominator.replace(0, np.nan)


def _compute(block: ExpressionBlock, sub: pd.DataFrame) -> pd.Series:
    op = block.op
    if op == "spread":
        mid = (sub["bid_price1"] + sub["ask_price1"]) / 2
        return _safe_divide(sub["ask_price1"] - sub["bid_price1"], mid)
    if op == "mid_price":
        return (sub["bid_price1"] + sub["ask_price1"]) / 2
    if op == "order_book_imbalance":
        return _safe_divide(sub["bid_volume1"] - sub["ask_volume1"],
                            sub["bid_volume1"] + sub["ask_volume1"])
    if op == "order_count_imbalance":
        return _safe_divide(sub["bid_num_orders1"] - sub["ask_num_orders1"],
                            sub["bid_num_orders1"] + sub["ask_num_orders1"])
    if op == "depth":
        return sub["bid_volume1"] + sub["ask_volume1"]
    if op == "avg_trade_size":
        return _safe_divide(sub["amount"], sub["deal_number"])

    first = sub[block.inputs[0]].astype(float)
    if op == "raw":
        return first
    if op == "return":
        return first.pct_change(int(block.params["window"]), fill_method=None)
    if op == "volatility":
        returns = first.pct_change(fill_method=None)
        return returns.rolling(int(block.params["window"]), min_periods=2).std()
    if op == "rolling_mean":
        return first.rolling(int(block.params["window"]), min_periods=2).mean()
    if op == "rolling_std":
        return first.rolling(int(block.params["window"]), min_periods=2).std()
    if op == "rolling_sum":
        return first.rolling(int(block.params["window"]), min_periods=2).sum()
    if op == "ewm":
        return first.ewm(span=int(block.params["window"]), min_periods=2,
                         adjust=False).mean()
    if op == "diff":
        return first.diff()
    if op == "pct_change":
        return first.pct_change(fill_method=None)
    if op == "clip":
        return first.clip(float(block.params["lo"]), float(block.params["hi"]))
    second = sub[block.inputs[1]].astype(float)
    if op == "ratio":
        return _safe_divide(first, second)
    if op == "difference":
        return first - second
    if op == "product":
        return first * second
    raise ValueError(f"unsupported op: {op}")


def _required_columns(block: ExpressionBlock) -> set[str]:
    fixed = {
        "spread": {"bid_price1", "ask_price1"},
        "mid_price": {"bid_price1", "ask_price1"},
        "order_book_imbalance": {"bid_volume1", "ask_volume1"},
        "order_count_imbalance": {"bid_num_orders1", "ask_num_orders1"},
        "depth": {"bid_volume1", "ask_volume1"},
        "avg_trade_size": {"amount", "deal_number"},
    }
    return fixed.get(block.op, set(block.inputs))


def eval_block(block: ExpressionBlock, frame: pd.DataFrame,
               group_col: str = "instrument") -> pd.Series:
    required = _required_columns(block)
    missing = sorted(required.difference(frame.columns))
    if missing:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    result = pd.Series(np.nan, index=frame.index, dtype=float)
    ordered = frame.sort_values([group_col, "date"], kind="mergesort")
    for _, sub in ordered.groupby(group_col, sort=False):
        values = _compute(block, sub)
        result.loc[sub.index] = values.to_numpy(dtype=float)
    return result


def eval_genome(genome: Genome, frame: pd.DataFrame,
                group_col: str = "instrument") -> pd.Series:
    errors = validate_genome(genome)
    if errors:
        raise ValueError("invalid genome: " + "; ".join(errors))
    timestamps = pd.to_datetime(frame["date"])
    parts = []
    for block in genome.blocks:
        sign = 1.0 if block.sign == "+" else -1.0
        raw = eval_block(block, frame, group_col) * sign
        block_frame = pd.DataFrame(
            {"timestamp": timestamps, "value": raw}, index=frame.index)
        if genome.combine == "rank":
            normalized = (
                block_frame.groupby("timestamp")["value"].rank(pct=True) - 0.5
            )
        else:
            normalized = block_frame.groupby("timestamp")["value"].transform(
                lambda values: (
                    (values - values.mean()) / (values.std(ddof=0) + 1e-9)
                )
            )
        parts.append(normalized)
    signal = pd.concat(parts, axis=1).mean(axis=1, skipna=False)
    temp = pd.DataFrame({"timestamp": timestamps, "signal": signal}, index=frame.index)
    if genome.combine == "rank":
        return temp.groupby("timestamp")["signal"].rank(pct=True)
    # neutralize is deliberately a cross-sectional z-score locally.  Official
    # BARRA residualisation remains an external platform operation.
    return temp.groupby("timestamp")["signal"].transform(
        lambda values: (values - values.mean()) / (values.std(ddof=0) + 1e-9))
