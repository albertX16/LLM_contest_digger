"""Genome → 平台 Notebook 编译器。

把 GA 搜索出的 Genome 结构逐算子翻译成可在 BigQuant 平台 1m bar 数据上
直接运行的 pandas 代码，生成比赛格式的 .ipynb。翻译逻辑与 automation/evaluate/expr.py
严格对齐——同样的算子语义、同样的块组合方式、同样的截面聚合。
"""

from __future__ import annotations

import json
from pathlib import Path

from automation.search.genome import Genome, ExpressionBlock

# Local research uses 30m bars and the platform submission data uses 1m bars.
BAR_SCALE = 30


def block_to_pandas(block: ExpressionBlock, var: str, df_var: str = "df",
                    group_col: str = "instrument", bar_scale: int = BAR_SCALE) -> list[str]:
    """将一个 ExpressionBlock 翻译成 pandas 代码行列表。

    返回的代码将因子值写入变量 `var`（如 "b1"）。
    """
    op = block.op
    inputs = block.inputs
    params = block.params
    sign = 1.0 if block.sign == "+" else -1.0
    lines: list[str] = []

    # ── 盘口衍生算子（从 bid/ask 列计算）──
    if op == "spread":
        lines.append(f"# spread = (ask_price1 - bid_price1) / mid")
        lines.append(f"_mid = ({df_var}['bid_price1'] + {df_var}['ask_price1']) / 2")
        lines.append(f"{var} = ({df_var}['ask_price1'] - {df_var}['bid_price1']) / _mid.replace(0, np.nan) * {sign}")
        return lines
    if op == "mid_price":
        lines.append(f"# mid_price = (bid_price1 + ask_price1) / 2")
        lines.append(f"{var} = ({df_var}['bid_price1'] + {df_var}['ask_price1']) / 2 * {sign}")
        return lines
    if op == "order_book_imbalance":
        lines.append(f"# OBI = (bid_vol1 - ask_vol1) / (bid_vol1 + ask_vol1)")
        lines.append(f"_num = {df_var}['bid_volume1'] - {df_var}['ask_volume1']")
        lines.append(f"_den = {df_var}['bid_volume1'] + {df_var}['ask_volume1']")
        lines.append(f"{var} = (_num / _den.replace(0, np.nan)) * {sign}")
        return lines
    if op == "order_count_imbalance":
        lines.append("# order-count imbalance at level 1")
        lines.append(f"_num = {df_var}['bid_num_orders1'] - {df_var}['ask_num_orders1']")
        lines.append(f"_den = {df_var}['bid_num_orders1'] + {df_var}['ask_num_orders1']")
        lines.append(f"{var} = (_num / _den.replace(0, np.nan)) * {sign}")
        return lines
    if op == "depth":
        lines.append(f"# depth = bid_volume1 + ask_volume1")
        lines.append(f"{var} = ({df_var}['bid_volume1'] + {df_var}['ask_volume1']) * {sign}")
        return lines
    if op == "avg_trade_size":
        lines.append("# average notional per print")
        lines.append(f"{var} = ({df_var}['amount'] / {df_var}['deal_number'].replace(0, np.nan)) * {sign}")
        return lines

    # ── 返回类算子（基于 close，per-instrument）──
    if op == "return":
        w_raw = int(params.get("window", 1))
        w = w_raw * bar_scale
        lines.append(f"# {op} → pct_change({w}) per instrument")
        col = inputs[0]
        lines.append(f"{var} = {df_var}.groupby('{group_col}')['{col}'].pct_change({w}, fill_method=None) * {sign}")
        return lines

    # ── 波动率类算子（per-instrument rolling std）──
    if op == "volatility":
        w_raw = int(params.get("window", 5))
        w = max(1, w_raw * bar_scale)
        lines.append(f"# {op}(window={w_raw}→{w}) → rolling({w}).std() per instrument")
        col = inputs[0]
        lines.append(f"{var} = {df_var}.groupby('{group_col}')['{col}'].transform(")
        lines.append(f"    lambda x: x.pct_change(fill_method=None).rolling({w}, min_periods=2).std()) * {sign}")
        return lines

    # ── 窗口聚合算子（per-instrument）──
    if op in ("rolling_sum", "rolling_mean", "rolling_std", "ewm"):
        w_raw = int(params.get("window", 5))
        w = max(1, w_raw * bar_scale)
        fn_map = {"rolling_sum": "sum", "rolling_mean": "mean", "rolling_std": "std", "ewm": "mean"}
        fn = fn_map[op]
        lines.append(f"# {op}(window={w_raw}→{w}) per instrument")
        if inputs:
            cols_str = str(inputs)
            col_ref = f"{df_var}[{cols_str}].mean(axis=1)" if len(inputs) > 1 else f"{df_var}['{inputs[0]}']"
            lines.append(f"_base_{var} = {col_ref}")
        else:
            lines.append(f"_base_{var} = {df_var}['close']")
        lines.append(f"{var} = _base_{var}.groupby({df_var}['{group_col}']).transform(")
        if op == "ewm":
            lines.append(f"    lambda x: x.ewm(span={w}, min_periods=2, adjust=False).mean()) * {sign}")
        else:
            lines.append(f"    lambda x: x.rolling({w}, min_periods=2).{fn}()) * {sign}")
        return lines

    # ── 逐行算子 ──
    if op == "diff":
        if inputs:
            col = inputs[0]
            lines.append(
                f"# diff per instrument on {col}"
            )
            lines.append(
                f"{var} = {df_var}.groupby('{group_col}')['{col}'].diff({bar_scale}) * {sign}"
            )
        else:
            lines.append(
                f"{var} = {df_var}.groupby('{group_col}')['close'].diff({bar_scale}) * {sign}"
            )
        return lines

    if op == "pct_change":
        if inputs:
            col = inputs[0]
            lines.append(
                f"# pct_change per instrument on {col}"
            )
            lines.append(
                f"{var} = {df_var}.groupby('{group_col}')['{col}'].pct_change({bar_scale}, fill_method=None) * {sign}"
            )
        else:
            lines.append(
                f"{var} = {df_var}.groupby('{group_col}')['close'].pct_change({bar_scale}, fill_method=None) * {sign}"
            )
        return lines

    if op == "clip":
        lo = params.get("lo", -3.0)
        hi = params.get("hi", 3.0)
        col = inputs[0] if inputs else "close"
        lines.append(f"# clip({lo}, {hi})")
        lines.append(f"{var} = {df_var}['{col}'].clip({lo}, {hi}) * {sign}")
        return lines

    if op in ("ratio", "difference", "product"):
        left, right = inputs
        if op == "ratio":
            lines.append(f"{var} = ({df_var}['{left}'] / {df_var}['{right}'].replace(0, np.nan)) * {sign}")
        elif op == "difference":
            lines.append(f"{var} = ({df_var}['{left}'] - {df_var}['{right}']) * {sign}")
        else:
            lines.append(f"{var} = ({df_var}['{left}'] * {df_var}['{right}']) * {sign}")
        return lines

    if op == "raw":
        col = inputs[0]
        return [f"# raw column: {col}", f"{var} = {df_var}['{col}'] * {sign}"]
    raise ValueError(f"unsupported notebook op: {op}")


def combine_to_pandas(combine: str, signal_var: str = "signal",
                      factor_var: str = "factor",
                      df_var: str = "df") -> list[str]:
    """将 combine 算子翻译成 pandas 截面聚合代码。"""
    lines: list[str] = []
    if combine == "zscore":
        lines.append(f"# combine=zscore: 同一分钟截面标准化（禁止使用日内未来样本）")
        lines.append(f"{factor_var} = {df_var}.groupby({df_var}['date'])['{signal_var}'].transform(")
        lines.append(f"    lambda x: (x - x.mean()) / (x.std() + 1e-9))")
    elif combine == "rank":
        lines.append(f"# combine=rank: 同一分钟截面百分位排名")
        lines.append(f"{factor_var} = {df_var}.groupby({df_var}['date'])['{signal_var}'].rank(pct=True)")
    elif combine == "neutralize":
        lines.append(f"# combine=neutralize: 同一分钟截面 zscore（平台会再做 BARRA 中性化）")
        lines.append(f"{factor_var} = {df_var}.groupby({df_var}['date'])['{signal_var}'].transform(")
        lines.append(f"    lambda x: (x - x.mean()) / (x.std() + 1e-9))")
    else:
        raise ValueError(f"unsupported combine: {combine}")
    return lines


def genome_to_notebook(genome: Genome, factor_id: str, local_metrics: dict,
                       round_no: int = 0) -> str:
    """将完整 genome 编译为平台 notebook 的 Python 源码字符串。"""
    lines: list[str] = []

    # ── 收集需要的列 ──
    needed_cols: set[str] = set()
    for block in genome.blocks:
        for c in block.inputs:
            needed_cols.add(c)
        if block.op in ("return", "volatility"):
            needed_cols.update(block.inputs)
        if block.op in ("spread", "mid_price"):
            needed_cols.update(["bid_price1", "ask_price1"])
        if block.op in ("order_book_imbalance", "depth"):
            needed_cols.update(["bid_volume1", "ask_volume1"])
        if block.op == "order_count_imbalance":
            needed_cols.update(["bid_num_orders1", "ask_num_orders1"])
        if block.op == "avg_trade_size":
            needed_cols.update(["amount", "deal_number"])
    # Also include the op name itself if it's a raw column reference
    for block in genome.blocks:
        if block.op not in ("spread", "mid_price", "order_book_imbalance", "order_count_imbalance", "depth", "avg_trade_size",
                            "diff", "pct_change", "clip",
                            "rolling_sum", "rolling_mean", "rolling_std", "ewm",
                            "return", "volatility", "ratio", "difference", "product", "raw"):
            raise ValueError(f"unsupported op while collecting columns: {block.op}")

    ordered_cols = sorted(needed_cols)
    sum_fields = {"volume", "amount", "deal_number"}
    aggregate_expr = []
    for column in ordered_cols:
        if column in sum_fields:
            aggregate_expr.append(
                f"SUM(CAST({column} AS DOUBLE)) AS {column}")
        elif column == "high":
            aggregate_expr.append("MAX(CAST(high AS DOUBLE)) AS high")
        elif column == "low":
            aggregate_expr.append("MIN(CAST(low AS DOUBLE)) AS low")
        elif column == "open":
            aggregate_expr.append("ARG_MIN(CAST(open AS DOUBLE), date) AS open")
        else:
            aggregate_expr.append(
                f"ARG_MAX(CAST({column} AS DOUBLE), date) AS {column}")

    # ── Header ──
    hypothesis_parts = []
    for b in genome.blocks:
        hypothesis_parts.append(f"{b.op}({','.join(b.inputs) if b.inputs else 'auto'}){b.sign}")
    hypothesis = " + ".join(hypothesis_parts)

    lines.append('"""BigAlpha 2026 AI Track')
    lines.append(f'Factor ID: {factor_id}')
    lines.append(f'Strategy: {hypothesis}')
    lines.append(f'Combine: {genome.combine} | Blocks: {len(genome.blocks)}')
    if local_metrics:
        lines.append(f'Local fitness: {local_metrics.get("fitness",0):.4f} | '
                     f'rank_ic: {local_metrics.get("rank_ic",0):.4f} | '
                     f'rank_ic_ir: {local_metrics.get("rank_ic_ir",0):.4f}')
    lines.append('"""')
    lines.append('import numpy as np')
    lines.append('import pandas as pd')
    lines.append('import dai')
    lines.append('')
    lines.append('')
    lines.append('def main(datasources, start_date, end_date):')
    lines.append(f'    """Factor: {factor_id} — {hypothesis}"""')
    lines.append('    bar1m = datasources["bar1m"]')
    lines.append('')
    lines.append('    sql = f"""')
    lines.append('    WITH raw AS (')
    lines.append('        SELECT')
    lines.append('            date, instrument, CAST(date AS DATE) AS d,')
    lines.append('            CAST(EXTRACT(HOUR FROM date) AS INTEGER) * 100')
    lines.append('                + CAST(EXTRACT(MINUTE FROM date) AS INTEGER) AS hhmm,')
    lines.append('            CAST(EXTRACT(HOUR FROM date) AS INTEGER) * 60')
    lines.append('                + CAST(EXTRACT(MINUTE FROM date) AS INTEGER) AS minute_of_day,')
    for index, column in enumerate(ordered_cols):
        comma = ',' if index < len(ordered_cols) - 1 else ''
        lines.append(f'            {column}{comma}')
    lines.append('        FROM {bar1m}')
    lines.append('    ),')
    lines.append('    tagged AS (')
    lines.append('        SELECT *, CASE')
    lines.append('            WHEN hhmm BETWEEN 931 AND 1130')
    lines.append('                THEN CAST(FLOOR((minute_of_day - 571) / 30.0) AS INTEGER)')
    lines.append('            WHEN hhmm BETWEEN 1301 AND 1500')
    lines.append('                THEN 4 + CAST(FLOOR((minute_of_day - 781) / 30.0) AS INTEGER)')
    lines.append('        END AS block_id')
    lines.append('        FROM raw')
    lines.append('        WHERE (hhmm BETWEEN 931 AND 1130)')
    lines.append('           OR (hhmm BETWEEN 1301 AND 1500)')
    lines.append('    ),')
    lines.append('    bar30m AS (')
    lines.append('        SELECT d, instrument, block_id, MAX(date) AS date,')
    for index, expression in enumerate(aggregate_expr):
        comma = ',' if index < len(aggregate_expr) - 1 else ''
        lines.append(f'            {expression}{comma}')
    lines.append('        FROM tagged')
    lines.append('        GROUP BY d, instrument, block_id')
    lines.append('    )')
    lines.append('    SELECT date, instrument, ' + ', '.join(ordered_cols))
    lines.append('    FROM bar30m')
    lines.append('    ORDER BY date, instrument')
    lines.append('    """')
    lines.append('')
    lines.append('    df = dai.query(')
    lines.append('        sql,')
    lines.append('        filters={"date": [start_date, end_date]},')
    lines.append('        compression=True,')
    lines.append('    ).df()')
    lines.append('')
    lines.append('    df["date"] = pd.to_datetime(df["date"])')
    lines.append('    df["instrument"] = df["instrument"].astype(str)')
    lines.append('    df = df.sort_values(["instrument", "date"], kind="mergesort")')
    lines.append('')

    # ── Block 计算 ──
    for i, block in enumerate(genome.blocks):
        var = f"b{i+1}"
        lines.append(f'    # ── Block {i+1}: {block.op} sign={block.sign} inputs={block.inputs} ──')
        blk_lines = block_to_pandas(block, var, bar_scale=1)
        for l in blk_lines:
            lines.append(f"    {l}")
        if genome.combine == "rank":
            lines.append(
                f"    {var} = {var}.groupby(df['date']).rank(pct=True) - 0.5"
            )
        else:
            lines.append(f"    {var} = {var}.groupby(df['date']).transform(")
            lines.append(
                "        lambda x: (x - x.mean()) / (x.std(ddof=0) + 1e-9))"
            )
        lines.append('')

    # ── 组合块 → signal ──
    n = len(genome.blocks)
    parts = " + ".join(f"b{i+1}" for i in range(n))
    lines.append(f'    # ── 组合 {n} 块 → signal（等权平均）──')
    lines.append(f'    signal = ({parts}) / {n}')
    lines.append(f'    df["signal"] = signal')
    lines.append('')

    # ── 截面聚合 ──
    lines.append(f'    # ── 截面聚合: {genome.combine} ──')
    combine_lines = combine_to_pandas(genome.combine)
    for l in combine_lines:
        lines.append(f"    {l}")
    lines.append('')

    # ── 日频输出 ──
    lines.append('    # ── 日频聚合：每日每股票取第8根精确30m bar ──')
    lines.append('    df["trade_date"] = df["date"].dt.date')
    lines.append('    output = (')
    lines.append('        df[["trade_date", "instrument", "factor"]]')
    lines.append('        .groupby(["trade_date", "instrument"], sort=False)')
    lines.append('        .last()')
    lines.append('        .reset_index()')
    lines.append('    )')
    lines.append('    output = output.rename(columns={"trade_date": "date"})')
    lines.append('    output["date"] = pd.to_datetime(output["date"])')
    lines.append('    pool = dai.query(')
    lines.append('        "SELECT date, instrument FROM bigalpha_2026_instruments",')
    lines.append('        filters={"date": [start_date, end_date]}, compression=True,')
    lines.append('    ).df()')
    lines.append('    pool["date"] = pd.to_datetime(pool["date"])')
    lines.append('    pool["instrument"] = pool["instrument"].astype(str)')
    lines.append('    output = pool.merge(output, how="left", on=["date", "instrument"])')
    lines.append('    output["factor"] = pd.to_numeric(')
    lines.append('        output["factor"], errors="coerce"')
    lines.append('    ).replace([np.inf, -np.inf], np.nan).fillna(0.0)')
    lines.append('')
    lines.append('    return (')
    lines.append('        output[["date", "instrument", "factor"]]')
    lines.append('        .drop_duplicates(["date", "instrument"], keep="last")')
    lines.append('        .sort_values(["date", "instrument"])')
    lines.append('        .reset_index(drop=True)')
    lines.append('    )')
    lines.append('')

    return '\n'.join(lines)


def genome_notebook_to_ipynb(source: str) -> dict:
    """将源码字符串打包为 .ipynb JSON。"""
    return {
        "cells": [{
            "id": "factor-code",
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [line + '\n' for line in source.split('\n')]
        }],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.11.0"}
        },
        "nbformat": 4,
        "nbformat_minor": 5
    }
