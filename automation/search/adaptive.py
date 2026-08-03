"""Persistent component credit used by generation and mutation.

The table deliberately stores evidence at the smallest reusable DSL units
(operator, field, window, sign, combine and block motif).  Scores are converted
to within-batch ranks before updating, so a noisy high-scale round cannot erase
all earlier evidence.  Sampling always mixes the learned distribution with a
uniform exploration floor; the floor is an explicit search policy, not a
fallback path.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable

from .genome import Genome


@dataclass
class CreditStat:
    observations: int = 0
    mean_reward: float = 0.0
    ewma_reward: float = 0.0
    positive: int = 0
    last_round: int = 0

    def update(self, reward: float, *, learning_rate: float, round_no: int) -> None:
        reward = float(max(-1.0, min(1.0, reward)))
        self.observations += 1
        self.mean_reward += (reward - self.mean_reward) / self.observations
        if self.observations == 1:
            self.ewma_reward = reward
        else:
            self.ewma_reward = (
                learning_rate * reward + (1.0 - learning_rate) * self.ewma_reward
            )
        self.positive += int(reward > 0)
        self.last_round = max(self.last_round, int(round_no))

    def to_dict(self) -> dict[str, Any]:
        return {
            "observations": self.observations,
            "mean_reward": self.mean_reward,
            "ewma_reward": self.ewma_reward,
            "positive": self.positive,
            "last_round": self.last_round,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CreditStat":
        return cls(
            observations=int(raw["observations"]),
            mean_reward=float(raw["mean_reward"]),
            ewma_reward=float(raw["ewma_reward"]),
            positive=int(raw["positive"]),
            last_round=int(raw.get("last_round", 0)),
        )


@dataclass
class ComponentCreditTable:
    exploration_floor: float = 0.15
    learning_rate: float = 0.25
    temperature: float = 0.35
    stats: dict[str, dict[str, CreditStat]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 < self.exploration_floor <= 1.0:
            raise ValueError("exploration_floor 必须在 (0, 1] 内")
        if not 0.0 < self.learning_rate <= 1.0:
            raise ValueError("credit_learning_rate 必须在 (0, 1] 内")
        if self.temperature <= 0:
            raise ValueError("credit_temperature 必须 > 0")

    @staticmethod
    def _components(genome: Genome) -> dict[str, list[str]]:
        components: dict[str, list[str]] = {
            "combine": [genome.combine],
            "block_count": [str(len(genome.blocks))],
            "op": [],
            "field": [],
            "window": [],
            "sign": [],
            "motif": [],
        }
        for block in genome.blocks:
            components["op"].append(block.op)
            components["field"].extend(block.inputs)
            if "window" in block.params:
                components["window"].append(str(int(block.params["window"])))
            components["sign"].append(block.sign)
            motif_fields = ",".join(block.inputs) or "_"
            motif_window = str(int(block.params["window"])) if "window" in block.params else "_"
            components["motif"].append(
                f"{block.op}|{motif_fields}|w={motif_window}|s={block.sign}"
            )
        return components

    def update_genomes(
        self,
        ranked: list[tuple[Genome, float]],
        *,
        round_no: int = 0,
    ) -> None:
        """Credit every reusable component with a rank-normalized reward."""
        if not ranked:
            return
        ordered = sorted(ranked, key=lambda item: float(item[1]))
        denominator = max(1, len(ordered) - 1)
        positions_by_score: dict[float, list[int]] = {}
        for position, (_genome, score) in enumerate(ordered):
            positions_by_score.setdefault(float(score), []).append(position)
        reward_by_score = {
            score: (2.0 * (sum(positions) / len(positions)) / denominator - 1.0
                    if len(ordered) > 1 else 0.0)
            for score, positions in positions_by_score.items()
        }
        for position, (genome, _score) in enumerate(ordered):
            reward = reward_by_score[float(_score)]
            for kind, values in self._components(genome).items():
                # A repeated field in one genome is one piece of evidence, not
                # several independent observations.
                for value in dict.fromkeys(values):
                    self.update(kind, value, reward, round_no=round_no)

    def update(self, kind: str, value: str, reward: float, *, round_no: int = 0) -> None:
        bucket = self.stats.setdefault(str(kind), {})
        stat = bucket.setdefault(str(value), CreditStat())
        stat.update(reward, learning_rate=self.learning_rate, round_no=round_no)

    def probabilities(self, kind: str, values: Iterable[Any]) -> list[float]:
        candidates = [str(value) for value in values]
        if not candidates:
            raise ValueError(f"{kind} 候选集合为空")
        bucket = self.stats.get(kind, {})
        logits = [
            bucket[value].ewma_reward / self.temperature if value in bucket else 0.0
            for value in candidates
        ]
        peak = max(logits)
        learned = [math.exp(value - peak) for value in logits]
        total = sum(learned)
        learned = [value / total for value in learned]
        uniform = 1.0 / len(candidates)
        floor = self.exploration_floor
        return [(1.0 - floor) * value + floor * uniform for value in learned]

    def choose(self, rng, kind: str, values: Iterable[Any]) -> str:
        candidates = tuple(str(value) for value in values)
        probabilities = self.probabilities(kind, candidates)
        return str(rng.choice(candidates, p=probabilities))

    def top(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = [
            {"kind": kind, "value": value, **stat.to_dict()}
            for kind, bucket in self.stats.items()
            for value, stat in bucket.items()
        ]
        rows.sort(
            key=lambda row: (row["ewma_reward"], row["observations"]), reverse=True
        )
        return rows[:limit]

    def to_dict(self) -> dict[str, Any]:
        return {
            "exploration_floor": self.exploration_floor,
            "learning_rate": self.learning_rate,
            "temperature": self.temperature,
            "stats": {
                kind: {value: stat.to_dict() for value, stat in bucket.items()}
                for kind, bucket in self.stats.items()
            },
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ComponentCreditTable":
        table = cls(
            exploration_floor=float(raw["exploration_floor"]),
            learning_rate=float(raw["learning_rate"]),
            temperature=float(raw["temperature"]),
        )
        table.stats = {
            str(kind): {
                str(value): CreditStat.from_dict(stat)
                for value, stat in bucket.items()
            }
            for kind, bucket in raw.get("stats", {}).items()
        }
        return table
