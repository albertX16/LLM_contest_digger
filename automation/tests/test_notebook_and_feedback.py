from __future__ import annotations

import ast

from automation.loop.genome_to_notebook import genome_notebook_to_ipynb, genome_to_notebook
from automation.loop.run_round import RoundRunner
from automation.search.genome import ExpressionBlock, Genome


def test_generated_notebook_is_submission_shaped_and_future_safe() -> None:
    genome = Genome([
        ExpressionBlock("order_book_imbalance", [], {}, "+"),
        ExpressionBlock("rolling_std", ["volume"], {"window": 5}, "-"),
    ], "rank")
    source = genome_to_notebook(genome, "factor_x", {"fitness": 1, "rank_ic": .02,
                                                     "rank_ic_ir": .3}, 1)
    tree = ast.parse(source)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    assert [node.name for node in functions] == ["main"]
    assert "groupby(df['date'])" in source
    assert ".shift(-" not in source
    assert "bid_volume1, volume" in source
    notebook = genome_notebook_to_ipynb(source)
    assert notebook["nbformat"] == 4
    assert len(notebook["cells"]) == 1
    assert notebook["cells"][0]["id"] == "factor-code"


def test_intraday_step_ops_preserve_30m_semantics_on_1m_platform_bars() -> None:
    genome = Genome([
        ExpressionBlock("pct_change", ["volume"], {}, "+"),
        ExpressionBlock("diff", ["close"], {}, "-"),
    ], "rank")
    source = genome_to_notebook(genome, "factor_step", {}, 1)
    assert "bar30m AS" in source
    assert "hhmm BETWEEN 931 AND 1130" in source
    assert ".pct_change(1, fill_method=None)" in source
    assert "['close'].diff(1)" in source
    assert "每日每股票取第8根精确30m bar" in source


def test_round_feedback_contains_machine_evidence_and_agent_advice() -> None:
    records = [
        {"factor_id": "keep", "verdict": "keep", "metrics": {"fitness": 3.0}},
        {"factor_id": "dead", "verdict": "retire", "metrics": {"fitness": -1.0},
         "kill_reason": "crowded"},
    ]
    summary = {"next_round_advice": ["reduce crowding"]}
    diagnostics = RoundRunner._next_diagnostics(records, summary)
    assert diagnostics["kept_count"] == 1
    assert diagnostics["retirement_reasons"] == ["crowded"]
    assert diagnostics["summarizer_advice"] == summary


def test_stage1_contract_reject_is_not_confused_with_unneutralized_scoring() -> None:
    RoundRunner._validate_score_contract({
        "stage_reached": 1, "passed": False,
        "reject_reason": "contract", "contract_failures": ["too sparse"],
        "preprocessing": {},
    })
    try:
        RoundRunner._validate_score_contract({
            "stage_reached": 2, "passed": False,
            "reject_reason": "quick fail", "preprocessing": {"neutralized": False},
        })
    except RuntimeError as exc:
        assert "未执行风险残差化" in str(exc)
    else:
        raise AssertionError("stage 2 unneutralized score must remain fatal")
