"""MAP-Elites 竞争网格：用 return-space 签名把因子分到格子，同类竞争。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Cell:
    """一个 return-space 格子，只保留该格内最好的因子。"""

    key: tuple[Any, ...]
    best: dict[str, Any] | None = None
    best_score: float = -math.inf


class MapElitesArchive:
    """简化 MAP-Elites：feature vector → cell，每 cell 保留最优。"""

    def __init__(self, n_bins: int = 8, limit: int = 200) -> None:
        self.n_bins = n_bins
        self.limit = limit
        self.cells: dict[tuple[Any, ...], Cell] = {}

    @staticmethod
    def discretize(value: float, lo: float = -3.0, hi: float = 3.0, bins: int = 8) -> int:
        """把连续值离散到 [0, bins-1]。"""
        if math.isnan(value):
            return bins // 2
        clipped = max(lo, min(hi, value))
        idx = int((clipped - lo) / (hi - lo) * bins)
        return max(0, min(bins - 1, idx))

    def cell_key(self, feature: dict[str, float]) -> tuple[Any, ...]:
        """把 feature 向量（如 {ic, turnover}）映射成格子 key。"""
        ranges = {
            "rank_ic_ir": (-1.0, 1.0),
            "max_corr_refset": (0.0, 1.0),
            "complexity": (1.0, 4.0),
        }
        key = []
        for name in sorted(feature):
            lo, hi = ranges.get(name, (-3.0, 3.0))
            key.append(self.discretize(float(feature[name]), lo, hi, self.n_bins))
        return tuple(key)

    def add(self, factor_id: str, feature: dict[str, float], score: float,
            payload: Any | None = None) -> bool:
        """返回是否成为该格新 best。"""
        key = self.cell_key(feature)
        cell = self.cells.setdefault(key, Cell(key=key))
        if score > cell.best_score:
            cell.best = {"id": factor_id, "feature": feature, "score": score,
                         "payload": payload}
            cell.best_score = score
            return True
        return False

    def best_of_cells(self) -> list[dict[str, Any]]:
        out = []
        for cell in self.cells.values():
            if cell.best is not None:
                out.append(cell.best)
        out.sort(key=lambda x: x["score"], reverse=True)
        return out[: self.limit]

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_bins": self.n_bins,
            "limit": self.limit,
            "cells": [
                {
                    "key": list(cell.key),
                    "best": cell.best,
                    "best_score": cell.best_score,
                }
                for cell in self.cells.values()
            ],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "MapElitesArchive":
        archive = cls(n_bins=int(raw["n_bins"]), limit=int(raw["limit"]))
        for item in raw.get("cells", []):
            key = tuple(item["key"])
            cell = Cell(
                key=key,
                best=item.get("best"),
                best_score=float(item.get("best_score", -math.inf)),
            )
            archive.cells[key] = cell
        return archive
