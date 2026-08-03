"""score_factor 的本地包装：让 GA 的候选因子能批量过 repo 的三级联评分。"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

# 把 repo 的 eval 包挂进 sys.path（只读复用，不拷贝）
REPO_EVAL = (
    Path(__file__).resolve().parents[2]
    / "bigalpha2026_main_src/bigalpha2026-main/eval"
)
if str(REPO_EVAL) not in sys.path:
    sys.path.insert(0, str(REPO_EVAL))

from scorer import score_factor  # noqa: E402
from scorer.cascade import ScoreConfig  # noqa: E402


def score_config_from_dict(values: dict | None) -> ScoreConfig:
    values = values or {}
    mapping = {
        "quick_window": "quick_window",
        "en_alpha": "en_alpha",
        "en_l1_ratio": "en_l1_ratio",
        "corr_gate": "corr_cap",
        "spanning_r2_max": "max_spanned_r2",
        "spanning_t_min": "min_residual_tstat",
        "pfs_min": "min_pfs",
    }
    kwargs = {target: values[source] for source, target in mapping.items()
              if source in values}
    return ScoreConfig(**kwargs)


def score_candidate(
    factor_id: str,
    factor_panel: pd.DataFrame,   # (date, instrument, factor)
    ret_panel: pd.DataFrame,      # (date, instrument, ret_fwd)
    refset: dict[str, pd.DataFrame] | None = None,
    exposures: dict[str, pd.DataFrame] | None = None,
    config: ScoreConfig | None = None,
) -> dict:
    """返回 QualityVector 的 dict 形式（便于写入 ledger）。"""
    if not exposures:
        raise ValueError("严格评分要求非空风险 exposures；禁止 raw 评分降级")
    qv = score_factor(factor_id, factor_panel, ret_panel, refset=refset,
                      exposures=exposures, config=config)
    return qv.to_dict() if hasattr(qv, "to_dict") else _qv_asdict(qv)


def _qv_asdict(qv) -> dict:
    from dataclasses import asdict

    return asdict(qv)
