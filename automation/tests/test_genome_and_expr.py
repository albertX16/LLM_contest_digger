from __future__ import annotations

import numpy as np
import pandas as pd

from automation.evaluate.expr import eval_genome
from automation.search.genome import (
    ExpressionBlock,
    Genome,
    constrain_to_columns,
    normalize_search_space,
    random_genome,
    validate_genome,
)


def _frame() -> pd.DataFrame:
    rows = []
    for step, timestamp in enumerate(pd.date_range("2023-01-02 10:00", periods=12, freq="30min")):
        for instrument, offset in (("A", 0.0), ("B", 10.0), ("C", 20.0)):
            rows.append({
                "date": timestamp,
                "instrument": instrument,
                "close": 100 + offset + step,
                "open": 99 + offset + step / 2,
                "volume": 10 + step,
                "amount": (100 + offset + step) * (10 + step),
                "deal_number": 2 + step,
                "bid_price1": 99 + offset + step,
                "ask_price1": 101 + offset + step,
                "bid_volume1": 20 + step,
                "ask_volume1": 10 + step,
                "bid_num_orders1": 8 + step,
                "ask_num_orders1": 4 + step,
            })
    return pd.DataFrame(rows)


def test_random_genomes_are_valid_even_with_one_planner_field() -> None:
    rng = np.random.default_rng(7)
    space = normalize_search_space({"search_space": {
        "allowed_ops": ["ratio", "return", "spread"],
        "allowed_fields": ["close"],
        "preferred_combines": ["rank"],
        "block_count": [1, 4],
    }})
    for _ in range(200):
        assert validate_genome(random_genome(rng, search_space=space)) == []


def test_actual_schema_removes_unavailable_fixed_ops_but_planner_mismatch_fails() -> None:
    default = normalize_search_space(None)
    constrained = constrain_to_columns(
        default,
        {"date", "instrument", "close", "open", "bid_price1", "ask_price1"},
        reject_missing_fields=False,
    )
    assert "spread" in constrained["allowed_ops"]
    assert "order_count_imbalance" not in constrained["allowed_ops"]
    try:
        constrain_to_columns(default, {"date", "instrument", "close"},
                             reject_missing_fields=True)
    except ValueError as exc:
        assert "不存在的字段" in str(exc)
    else:
        raise AssertionError("planner schema mismatch must fail")


def test_distinct_binary_operations_have_distinct_semantics() -> None:
    frame = _frame()
    ratio = Genome([ExpressionBlock("ratio", ["close", "open"], {})], "rank")
    difference = Genome([ExpressionBlock("difference", ["close", "open"], {})], "rank")
    ratio_values = eval_genome(ratio, frame)
    difference_values = eval_genome(difference, frame)
    assert not ratio_values.equals(difference_values)


def test_cross_section_is_exact_timestamp_not_whole_day() -> None:
    frame = _frame()
    genome = Genome([ExpressionBlock("raw", ["close"], {})], "rank")
    values = eval_genome(genome, frame)
    for _, positions in frame.groupby("date").groups.items():
        assert sorted(values.loc[positions].round(6).tolist()) == [0.333333, 0.666667, 1.0]
