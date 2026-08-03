"""Typed factor genome used by the local search and notebook compiler.

The first implementation mixed a column name (``op``) with unrelated random
``inputs``.  The evaluator consequently ignored much of the genome and many
different fingerprints produced the same factor.  This module defines a small,
explicit DSL: every operation has a fixed input arity and parameter contract.
Only genomes accepted by :func:`validate_genome` may enter the GA.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable


RAW_FIELDS: tuple[str, ...] = (
    "open", "high", "low", "close", "volume", "amount", "deal_number",
    "adjust_factor",
    "bid_price1", "bid_price2", "bid_price3",
    "ask_price1", "ask_price2", "ask_price3",
    "bid_volume1", "bid_volume2", "bid_volume3",
    "ask_volume1", "ask_volume2", "ask_volume3",
    "bid_num_orders1", "bid_num_orders2", "bid_num_orders3",
    "ask_num_orders1", "ask_num_orders2", "ask_num_orders3",
    # 1m -> 日频特征面板字段（2024 挖掘默认面板）
    "vwap", "avg_trade_size",
    "ret_open_close", "ret_open_vwap", "ret_close_vwap",
    "first30m_ret", "last30m_ret", "am_ret", "pm_ret",
    "close_pos_in_range",
    "volume_first30m_share", "volume_last30m_share", "volume_am_share",
    "amount_last30m_share", "deal_number_last30m_share",
    "rv_1m", "rv_am", "rv_pm",
    "mid_price", "spread", "spread_bps",
    "obi", "oci", "depth1", "depth_all",
    "bid_ask_vol_ratio1", "bid_ask_vol_ratio_all",
    "queue_imbalance_ask", "queue_imbalance_bid",
    "price_gap_ask", "price_gap_bid",
    "microprice", "microprice_premium",
    "avg_bid_volume1", "avg_ask_volume1",
    "avg_bid_num_orders1", "avg_ask_num_orders1",
    "avg_obi", "std_obi", "avg_oci", "avg_spread_bps",
)

DERIVED_OPS: tuple[str, ...] = (
    "spread", "mid_price", "order_book_imbalance", "order_count_imbalance",
    "depth", "avg_trade_size", "return", "volatility",
    "rolling_mean", "rolling_std", "rolling_sum", "ewm",
    "diff", "pct_change", "ratio", "difference", "product", "clip",
)
SUPPORTED_OPS: tuple[str, ...] = ("raw",) + DERIVED_OPS
COMBINE_OPS: tuple[str, ...] = ("zscore", "rank")

_NO_INPUT = {
    "spread", "mid_price", "order_book_imbalance", "order_count_imbalance",
    "depth", "avg_trade_size",
}
FIXED_OP_FIELDS: dict[str, set[str]] = {
    "spread": {"bid_price1", "ask_price1"},
    "mid_price": {"bid_price1", "ask_price1"},
    "order_book_imbalance": {"bid_volume1", "ask_volume1"},
    "order_count_imbalance": {"bid_num_orders1", "ask_num_orders1"},
    "depth": {"bid_volume1", "ask_volume1"},
    "avg_trade_size": {"amount", "deal_number"},
}
_ONE_INPUT = {
    "raw", "return", "volatility", "rolling_mean", "rolling_std",
    "rolling_sum", "ewm", "diff", "pct_change", "clip",
}
_TWO_INPUT = {"ratio", "difference", "product"}
_WINDOWED = {"return", "volatility", "rolling_mean", "rolling_std", "rolling_sum", "ewm"}


@dataclass
class ExpressionBlock:
    op: str
    inputs: list[str]
    params: dict[str, float]
    sign: str = "+"

    def to_expression(self) -> str:
        args = list(self.inputs)
        args.extend(f"{k}={v}" for k, v in sorted(self.params.items()))
        prefix = "-" if self.sign == "-" else ""
        return f"{prefix}{self.op}({', '.join(args)})"

    # Kept for compatibility with old ledgers.  This is a logical expression,
    # not executable DAI SQL; platform code must use genome_to_notebook.py.
    def to_sql(self) -> str:
        return self.to_expression()

    def to_dict(self) -> dict[str, Any]:
        return {"op": self.op, "inputs": list(self.inputs),
                "params": dict(self.params), "sign": self.sign}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExpressionBlock":
        return cls(op=str(data["op"]), inputs=list(data.get("inputs", [])),
                   params=dict(data.get("params", {})), sign=data.get("sign", "+"))


@dataclass
class Genome:
    blocks: list[ExpressionBlock] = field(default_factory=list)
    combine: str = "zscore"
    id: str = ""

    def to_expression(self) -> str:
        return f"{self.combine}((" + " + ".join(b.to_expression() for b in self.blocks) + ")/" + str(max(1, len(self.blocks))) + ")"

    def to_sql(self) -> str:
        return self.to_expression()

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "combine": self.combine,
                "blocks": [block.to_dict() for block in self.blocks]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Genome":
        return cls(blocks=[ExpressionBlock.from_dict(x) for x in data.get("blocks", [])],
                   combine=data.get("combine", "zscore"), id=data.get("id", ""))

    def fingerprint(self) -> str:
        raw = json.dumps({"combine": self.combine,
                          "blocks": [block.to_dict() for block in self.blocks]},
                         sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(raw.encode()).hexdigest()[:16]


def validate_block(block: ExpressionBlock) -> list[str]:
    errors: list[str] = []
    if block.op not in SUPPORTED_OPS:
        errors.append(f"unsupported op: {block.op}")
    if block.sign not in ("+", "-"):
        errors.append(f"invalid sign: {block.sign}")
    expected = 0 if block.op in _NO_INPUT else 1 if block.op in _ONE_INPUT else 2
    if len(block.inputs) != expected:
        errors.append(f"{block.op} expects {expected} inputs, got {len(block.inputs)}")
    unknown = [field for field in block.inputs if field not in RAW_FIELDS]
    if unknown:
        errors.append(f"unknown fields: {unknown}")
    if block.op in _WINDOWED:
        window = block.params.get("window")
        if not isinstance(window, (int, float)) or not 1 <= int(window) <= 60:
            errors.append(f"invalid window for {block.op}: {window}")
    if block.op == "clip" and float(block.params.get("lo", 0)) >= float(block.params.get("hi", 0)):
        errors.append("clip requires lo < hi")
    return errors


def validate_genome(genome: Genome) -> list[str]:
    errors = []
    if not 1 <= len(genome.blocks) <= 4:
        errors.append(f"genome requires 1..4 blocks, got {len(genome.blocks)}")
    if genome.combine not in COMBINE_OPS:
        errors.append(f"unsupported combine: {genome.combine}")
    for index, block in enumerate(genome.blocks):
        errors.extend(f"block[{index}]: {error}" for error in validate_block(block))
    return errors


def _choice(rng, values: Iterable[str], *, sampler=None, kind: str = "generic") -> str:
    values = tuple(values)
    if not values:
        raise ValueError("search space is empty")
    if sampler is not None:
        return sampler.choose(rng, kind, values)
    return str(rng.choice(values))


def random_block(rng, *, allowed_ops: Iterable[str] | None = None,
                 allowed_fields: Iterable[str] | None = None,
                 sampler=None) -> ExpressionBlock:
    ops = tuple(op for op in (allowed_ops or SUPPORTED_OPS) if op in SUPPORTED_OPS)
    fields = tuple(field for field in (allowed_fields or RAW_FIELDS) if field in RAW_FIELDS)
    op = _choice(rng, ops, sampler=sampler, kind="op")
    if op in _NO_INPUT:
        inputs: list[str] = []
    elif op in _TWO_INPUT:
        # A planner may legitimately narrow the field list to one item.  Binary
        # operators still need a type-correct pair, so repetition is preferable
        # to crashing the entire search round.
        first = _choice(rng, fields, sampler=sampler, kind="field")
        remaining = tuple(field for field in fields if field != first) or fields
        second = _choice(rng, remaining, sampler=sampler, kind="field")
        inputs = [first, second]
    else:
        inputs = [_choice(rng, fields, sampler=sampler, kind="field")]
    params: dict[str, float] = {}
    if op in _WINDOWED:
        params["window"] = int(_choice(
            rng, (2, 3, 5, 8, 13, 21, 34), sampler=sampler, kind="window"))
    elif op == "clip":
        params = {"lo": -3.0, "hi": 3.0}
    sign = _choice(rng, ("+", "-"), sampler=sampler, kind="sign")
    return ExpressionBlock(op=op, inputs=inputs, params=params, sign=sign)


def normalize_search_space(template: dict[str, Any] | None) -> dict[str, Any]:
    """Turn an optional planner response into a safe, executable search space."""
    if template is None:
        return {
            "allowed_ops": SUPPORTED_OPS,
            "allowed_fields": RAW_FIELDS,
            "preferred_combines": COMBINE_OPS,
            "block_count": (1, 3),
        }
    raw = (template or {}).get("search_space") or {}
    required = {"allowed_ops", "allowed_fields", "preferred_combines", "block_count"}
    missing_keys = sorted(required.difference(raw))
    if missing_keys:
        raise ValueError(f"planner search_space 缺字段: {missing_keys}")
    ops = list(raw["allowed_ops"])
    fields = list(raw["allowed_fields"])
    combines = list(raw["preferred_combines"])
    invalid_ops = sorted(set(ops).difference(SUPPORTED_OPS))
    invalid_fields = sorted(set(fields).difference(RAW_FIELDS))
    invalid_combines = sorted(set(combines).difference(COMBINE_OPS))
    if invalid_ops or invalid_fields or invalid_combines:
        raise ValueError(
            "planner search_space 含非法值: "
            f"ops={invalid_ops}, fields={invalid_fields}, combines={invalid_combines}"
        )
    if not ops or not fields or not combines:
        raise ValueError("planner search_space 不允许空操作/字段/合并集合")
    block_range = raw["block_count"]
    try:
        if len(block_range) != 2:
            raise ValueError
        lo, hi = int(block_range[0]), int(block_range[1])
    except (TypeError, ValueError, IndexError) as exc:
        raise ValueError("planner block_count 必须是两个整数") from exc
    if not (1 <= lo <= hi <= 4):
        raise ValueError(f"planner block_count 越界: {block_range}")
    return {
        "allowed_ops": tuple(ops),
        "allowed_fields": tuple(fields),
        "preferred_combines": tuple(combines),
        "block_count": (lo, hi),
    }


def random_genome(rng, n_blocks: int | None = None,
                  search_space: dict[str, Any] | None = None,
                  sampler=None) -> Genome:
    space = search_space or normalize_search_space(None)
    lo, hi = space["block_count"]
    count = int(n_blocks if n_blocks is not None else _choice(
        rng, tuple(str(value) for value in range(lo, hi + 1)),
        sampler=sampler, kind="block_count"))
    genome = Genome(
        blocks=[random_block(rng, allowed_ops=space["allowed_ops"],
                             allowed_fields=space["allowed_fields"],
                             sampler=sampler) for _ in range(max(1, count))],
        combine=_choice(rng, space["preferred_combines"],
                        sampler=sampler, kind="combine"),
    )
    errors = validate_genome(genome)
    if errors:
        raise ValueError("invalid generated genome: " + "; ".join(errors))
    return genome


def constrain_to_columns(
    search_space: dict[str, Any],
    columns: Iterable[str],
    *,
    reject_missing_fields: bool,
) -> dict[str, Any]:
    """Compile a validated search space against the actual panel schema."""
    available = set(columns)
    requested = tuple(search_space["allowed_fields"])
    missing = sorted(set(requested).difference(available))
    if missing and reject_missing_fields:
        raise ValueError(f"planner 请求了数据中不存在的字段: {missing}")
    fields = tuple(field for field in requested if field in available)
    if not fields:
        raise ValueError("实际 panel 与搜索字段没有交集")
    ops = tuple(
        op for op in search_space["allowed_ops"]
        if FIXED_OP_FIELDS.get(op, set()).issubset(available)
    )
    if not ops:
        raise ValueError("实际 panel 无法支持 planner 请求的任何算子")
    return {
        **search_space,
        "allowed_fields": fields,
        "allowed_ops": ops,
    }
