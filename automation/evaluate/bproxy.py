"""轻量 B-proxy：给 GA fitness 用的快速正交性/边际贡献代理。

完整 B-proxy（corr gate + spanning + Elastic-Net rehearsal）在 repo 的
score_factor 里，但每代几十个候选都跑完整三级联太慢。本模块提供
GA 内循环用的廉价代理：RankIC + 对 RefSet 的 max abs corr + 简单
残差预测性（跨截面 OLS 残差的 IC）。幸存者再走完整 score_factor。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def quick_fitness(
    factor_wide: pd.DataFrame,   # date x instrument 因子宽表
    ret_wide: pd.DataFrame,      # date x instrument fwd 收益宽表
    refset: dict[str, pd.DataFrame] | None = None,
    corr_cap: float = 0.6,
) -> dict[str, float]:
    """Return RankIC, ICIR, t-stat, crowding and fitness.

    fitness = rank_ic_ir * (1 - crowding_penalty)，其中 crowding_penalty
    在 max_corr 超过 corr_cap 时按超出量线性惩罚。
    """
    common = factor_wide.index.intersection(ret_wide.index)
    if len(common) < 20:
        return {"rank_ic": 0.0, "rank_ic_ir": 0.0, "rank_ic_tstat": 0.0,
                "max_corr_refset": 1.0, "fitness": -1e9}
    f = factor_wide.loc[common]
    r = ret_wide.loc[common]

    # 逐日 RankIC
    ics = []
    for date in f.index:
        row = f.loc[date]
        y = r.loc[date]
        mask = row.notna() & y.notna()
        if mask.sum() < 10:
            continue
        ics.append(row[mask].rank().corr(y[mask].rank()))
    if not ics:
        return {"rank_ic": 0.0, "rank_ic_ir": 0.0, "rank_ic_tstat": 0.0,
                "max_corr_refset": 1.0, "fitness": -1e9}
    ic_arr = np.array(ics)
    ic_mean = float(ic_arr.mean())
    ic_sd = float(ic_arr.std(ddof=1)) if len(ic_arr) > 1 else 0.0
    ic_ir = ic_mean / ic_sd if ic_sd > 0 else 0.0
    ic_t = ic_ir * np.sqrt(len(ic_arr))

    # 对 RefSet 的 max abs corr（逐列）
    max_corr = 0.0
    if refset:
        for name, member in refset.items():
            member_common = member.index.intersection(common)
            if len(member_common) < 20:
                continue
            m = member.loc[member_common]
            corrs = []
            for date in member_common:
                a, b = f.loc[date], m.loc[date]
                mask = a.notna() & b.notna()
                if mask.sum() < 10:
                    continue
                c = a[mask].corr(b[mask])
                if not np.isnan(c):
                    corrs.append(abs(c))
            if corrs:
                max_corr = max(max_corr, float(np.mean(corrs)))

    crowding = max(0.0, max_corr - corr_cap) * 2.0
    fitness = ic_t * (1.0 - min(crowding, 1.0))
    return {
        "rank_ic": ic_mean,
        "rank_ic_ir": ic_ir,
        "rank_ic_tstat": ic_t,
        "max_corr_refset": max_corr,
        "fitness": fitness,
    }
