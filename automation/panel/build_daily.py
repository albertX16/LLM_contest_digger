"""构建本地评估用的日频面板（parquet）。

产出：
- returns.parquet  (date, instrument, ret_fwd)  下一交易日收益
- factors/*.parquet 每个候选因子的 (date, instrument, factor)

因子的"本地求值"走 automation/evaluate/expr.py 的 pandas 语义近似
（与 DAI SQL 同义，具体实现见该模块）。
"""

from __future__ import annotations

import pandas as pd


def build_returns(daily_close: pd.DataFrame) -> pd.DataFrame:
    """从日频收盘构建 fwd 收益面板。"""
    wide = daily_close.pivot(index="date", columns="instrument", values="close")
    wide = wide.sort_index().ffill()
    ret = wide.pct_change().shift(-1)  # 下一交易日收益
    out = ret.stack(future_stack=True).rename("ret_fwd").reset_index()
    out.columns = ["date", "instrument", "ret_fwd"]
    return out.dropna().reset_index(drop=True)


def wide_factor(factor: pd.Series, name: str = "factor") -> pd.DataFrame:
    """把 (date, instrument, value) 因子转成 (date, instrument, factor)。"""
    return factor.rename(name).reset_index()
