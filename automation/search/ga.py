"""遗传算法主循环：种群进化，产出候选因子。

纯程序，不依赖 LLM。外部提供 fitness 函数（evaluate 层），
本模块只负责生成与演化 genome。
"""

from __future__ import annotations

import math
import logging
from collections.abc import Callable
from typing import Any

from .adaptive import ComponentCreditTable
from .genome import Genome, normalize_search_space, random_genome
from .operators import crossover, dedupe, mutate

log = logging.getLogger(__name__)


class GeneticSearch:
    def __init__(
        self,
        population_size: int = 24,
        generations: int = 20,
        elite_frac: float = 0.2,
        mutation_rate: float = 0.35,
        crossover_rate: float = 0.5,
        tournament_size: int = 3,
        seed: int = 20260801,
        exploration_floor: float = 0.15,
        credit_learning_rate: float = 0.25,
        credit_temperature: float = 0.35,
    ) -> None:
        import numpy as np

        self.rng = np.random.default_rng(seed)
        self.population_size = population_size
        self.generations = generations
        self.elite_count = max(1, int(population_size * elite_frac))
        self.mutation_rate = mutation_rate
        self.crossover_rate = crossover_rate
        self.tournament_size = tournament_size
        self._warm_start: list[Genome] = []
        self.credit = ComponentCreditTable(
            exploration_floor=exploration_floor,
            learning_rate=credit_learning_rate,
            temperature=credit_temperature,
        )

    def evolve(
        self,
        fitness: Callable[[list[Genome]], list[float]],
        *,
        search_space: dict | None = None,
        seed_genomes: list[Genome] | None = None,
        include_persistent_warm_start: bool = True,
        update_persistent_warm_start: bool = True,
        on_generation: Callable[[int, list[tuple[Genome, float]]], None] | None = None,
        round_no: int = 0,
    ) -> list[tuple[Genome, float]]:
        """跑完整演化，返回 (genome, fitness) 按 fitness 降序。"""
        space = normalize_search_space(None) if search_space is None else search_space
        allowed_ops = set(space["allowed_ops"])
        allowed_fields = set(space["allowed_fields"])
        allowed_combines = set(space["preferred_combines"])

        def fits_space(genome: Genome) -> bool:
            return (
                genome.combine in allowed_combines
                and all(block.op in allowed_ops for block in genome.blocks)
                and all(set(block.inputs).issubset(allowed_fields)
                        for block in genome.blocks)
            )

        initial = list(seed_genomes or [])
        if include_persistent_warm_start:
            initial.extend(self._warm_start)
        population = [Genome.from_dict(g.to_dict()) for g in initial
                      if fits_space(g)]
        population = dedupe(population)[:self.population_size]
        population.extend(random_genome(self.rng, search_space=space,
                                        sampler=self.credit)
                          for _ in range(self.population_size - len(population)))
        population = dedupe(population)
        while len(population) < self.population_size:
            population.append(random_genome(
                self.rng, search_space=space, sampler=self.credit))

        history: list[tuple[Genome, float]] = []
        lineage: dict[str, tuple[float, list[str]]] = {}
        for gen in range(self.generations):
            scores = fitness(population)
            ranked = sorted(zip(population, scores), key=lambda x: x[1], reverse=True)
            history.extend(ranked)
            self.credit.update_genomes(ranked, round_no=round_no)
            for genome, score in ranked:
                origin = lineage.get(genome.fingerprint())
                if origin is None:
                    continue
                parent_score, actions = origin
                scale = max(abs(parent_score), 1.0)
                reward = math.tanh((float(score) - parent_score) / scale)
                for action in dict.fromkeys(actions):
                    kind, value = action.split(":", 1)
                    self.credit.update(kind, value, reward, round_no=round_no)
            if on_generation:
                on_generation(gen + 1, ranked)
            log.info("gen %d: best=%.4f", gen + 1, ranked[0][1])

            elites = [g for g, _ in ranked[: self.elite_count]]
            offspring: list[Genome] = list(elites)
            next_lineage: dict[str, tuple[float, list[str]]] = {}
            score_by_fp = {genome.fingerprint(): float(score) for genome, score in ranked}
            while len(offspring) < self.population_size:
                a = self._tournament(ranked)
                b = self._tournament(ranked)
                learned_reproduction = self.credit.probabilities(
                    "reproduction", ("crossover", "clone"))[0]
                effective_crossover = min(0.95, max(
                    0.05,
                    self.crossover_rate + 0.5 * (learned_reproduction - 0.5),
                ))
                actions: list[str] = []
                if self.rng.random() < effective_crossover:
                    child = crossover(a, b, self.rng)
                    actions.append("reproduction:crossover")
                    parent_score = max(
                        score_by_fp[a.fingerprint()], score_by_fp[b.fingerprint()])
                else:
                    child = Genome.from_dict(a.to_dict())
                    actions.append("reproduction:clone")
                    parent_score = score_by_fp[a.fingerprint()]
                learned_mutation = self.credit.probabilities(
                    "mutation_intensity", ("mutate", "keep"))[0]
                effective_mutation = min(0.95, max(
                    0.05,
                    self.mutation_rate + 0.5 * (learned_mutation - 0.5),
                ))
                mutation_trace: list[str] = []
                child = mutate(
                    child, self.rng, effective_mutation, space,
                    sampler=self.credit, trace=mutation_trace,
                )
                if mutation_trace:
                    actions.append("mutation_intensity:mutate")
                    actions.extend(f"mutation_action:{action}" for action in mutation_trace)
                else:
                    actions.append("mutation_intensity:keep")
                offspring.append(child)
                next_lineage[child.fingerprint()] = (parent_score, actions)
            population = dedupe(offspring)
            while len(population) < self.population_size:
                population.append(random_genome(
                    self.rng, search_space=space, sampler=self.credit))
            lineage = next_lineage

        final_scores = fitness(population)
        final = sorted(zip(population, final_scores), key=lambda x: x[1], reverse=True)
        self.credit.update_genomes(final, round_no=round_no)
        for genome, score in final:
            origin = lineage.get(genome.fingerprint())
            if origin is None:
                continue
            parent_score, actions = origin
            reward = math.tanh((float(score) - parent_score) / max(abs(parent_score), 1.0))
            for action in dict.fromkeys(actions):
                kind, value = action.split(":", 1)
                self.credit.update(kind, value, reward, round_no=round_no)
        # 去重：同一指纹只保留 fitness 最高的版本，history 里的低分重复全部丢弃
        merged = final + history
        best_by_fp: dict[str, tuple[Genome, float]] = {}
        for genome, score in merged:
            fp = genome.fingerprint()
            if fp not in best_by_fp or score > best_by_fp[fp][1]:
                best_by_fp[fp] = (genome, score)
        ranked = sorted(best_by_fp.values(), key=lambda x: x[1], reverse=True)
        if update_persistent_warm_start:
            self._warm_start = [Genome.from_dict(genome.to_dict())
                                for genome, _ in ranked[: self.elite_count]]
        return ranked

    def set_warm_start_from_ranked(
        self, ranked: list[tuple[Genome, float]],
    ) -> None:
        """Commit cross-round seeds once, after all mechanisms finish."""
        ordered = sorted(ranked, key=lambda item: float(item[1]), reverse=True)
        seen: set[str] = set()
        retained: list[Genome] = []
        for genome, _score in ordered:
            fingerprint = genome.fingerprint()
            if fingerprint in seen:
                continue
            retained.append(Genome.from_dict(genome.to_dict()))
            seen.add(fingerprint)
            if len(retained) >= self.elite_count:
                break
        self._warm_start = retained

    def export_state(self) -> dict[str, Any]:
        return {
            "rng_state": self.rng.bit_generator.state,
            "warm_start": [genome.to_dict() for genome in self._warm_start],
            "component_credit": self.credit.to_dict(),
        }

    def load_state(self, raw: dict[str, Any]) -> None:
        required = {"rng_state", "warm_start", "component_credit"}
        missing = sorted(required.difference(raw))
        if missing:
            raise ValueError(f"GA 持久化状态缺字段: {missing}")
        self.rng.bit_generator.state = raw["rng_state"]
        self._warm_start = [Genome.from_dict(value) for value in raw["warm_start"]]
        self.credit = ComponentCreditTable.from_dict(raw["component_credit"])

    def discard_warm_start(self, fingerprints: set[str]) -> None:
        """Remove platform-confirmed failures from cross-round seeding."""
        rejected = {str(value) for value in fingerprints}
        self._warm_start = [
            genome for genome in self._warm_start
            if genome.fingerprint() not in rejected
        ]

    def _tournament(self, ranked: list[tuple[Genome, float]]) -> Genome:
        picks = self.rng.integers(0, len(ranked), size=self.tournament_size)
        best = max(picks, key=lambda i: ranked[i][1])
        return ranked[best][0]
