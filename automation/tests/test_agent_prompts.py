from __future__ import annotations

from pathlib import Path

from automation.agents.planner import _build_prompt as planner_prompt
from automation.agents.summarizer import (
    METRIC_GLOSSARY,
    SYSTEM_PROMPT as summarizer_prompt,
    _machine_bucket,
)


def test_planner_prompt_contains_research_boundaries_and_only_real_schema(tmp_path: Path) -> None:
    messages = planner_prompt(
        tmp_path / "memory.md", 1, {},
        ("close", "deal_number", "bid_volume1", "ask_volume1"),
        {"corr_gate": 0.6},
    )
    text = "\n".join(message["content"] for message in messages)
    assert "2024 全年 A 股 1 分钟 bar" in text
    assert "69 个日频特征" in text
    assert "Liu et al." in text
    assert "不能当作本项目翻转符号后的成功概率" in text
    assert "五档盘口" in text and "不得提出" in text
    assert "bid_volume1" in text
    assert "bid_volume3" not in text
    assert "不能读取另一个 block" in text
    assert "下一交易日收盘收益" in text
    assert '"corr_gate": 0.6' in text
    assert "PFS是对因子加入Gaussian" in text
    assert "每个 block 先在同一交易日" in text
    assert "不得读取或建议触碰 2025" in text
    assert "前沿研究建议" in text
    assert "SSRN 2024" in text and "Stoikov" in text
    assert "Heston" in text and "Alpha158" in text and "FactorMAD" in text
    assert "microprice_premium" in text
    assert "允许失败" in text
    assert "失败即冻结该方向" in text


def test_summarizer_prompt_freezes_failed_explore_families() -> None:
    assert "失败（verdict=retire）即冻结该方向" in summarizer_prompt
    assert "把预算留给更多不同的新机制" in summarizer_prompt
    assert "continue/repair" in summarizer_prompt


def test_summarizer_machine_bucket_respects_evidence() -> None:
    assert "不是官方B分" in METRIC_GLOSSARY["model_score"]
    assert "排序保真度" in METRIC_GLOSSARY["pfs"]
    crowded = {
        "metrics": {"max_corr_refset": 1.0},
        "preprocessing": {"neutralized": True},
    }
    assert _machine_bucket(crowded) == "crowded_duplicate"
    weak_prescreen = {
        "verdict": "retire", "metrics": {"rank_ic_tstat": -0.5},
        "preprocessing": {},
    }
    assert _machine_bucket(weak_prescreen) == "signal_weak"
    wrong_sign = {
        "verdict": "retire", "ex_ante_sign": "+", "sign_observed": "-",
        "metrics": {"neutralized_rank_ic_tstat": -2.1, "max_corr_refset": 0.2},
        "preprocessing": {"neutralized": True},
    }
    assert _machine_bucket(wrong_sign) == "wrong_sign_candidate"
