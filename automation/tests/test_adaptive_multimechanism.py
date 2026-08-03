from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from automation.agents.planner import PlannerAgent
from automation.loop.run_round import RoundRunner
from automation.search.adaptive import ComponentCreditTable
from automation.search.ga import GeneticSearch
from automation.search.genome import ExpressionBlock, Genome, normalize_search_space
from automation.search.map_elites import MapElitesArchive


def _genome(field: str, sign: str = "+") -> Genome:
    return Genome([ExpressionBlock("raw", [field], {}, sign)], "rank")


class _PlannerClient:
    def chat_json(self, messages, **_kwargs):
        prompt = "\n".join(message["content"] for message in messages)
        exploit = "轨道：exploit" in prompt
        slot = int(prompt.split("本轮机制槽位：", 1)[1].split("；", 1)[0])
        parent_ids = []
        if exploit:
            marker = "允许引用的历史父因子"
            block = prompt.split(marker, 1)[1].split("可信长期记忆", 1)[0]
            parent_ids = [json.loads(block.split("：\n", 1)[1])[0]["factor_id"]]
        prototype = _genome(
            "close" if slot % 2 else "volume",
            "+" if slot <= 2 else "-",
        )
        variant = _genome(
            "volume" if slot % 2 else "close",
            "+" if slot <= 2 else "-",
        )
        return {
            "research_track": "exploit" if exploit else "explore",
            "parent_factor_ids": parent_ids,
            "hypothesis": f"{'延续父机制' if exploit else '盘口新机制'}-{slot}",
            "ex_ante_sign": "+",
            "proposal_type": "repair" if exploit else "new_mechanism",
            "parent_mechanisms": ["A", "B"],
            "incremental_mechanism": "interaction",
            "falsifier": "residual IC disappears",
            "transfer_caveat": "30m only",
            "search_space": {
                "allowed_ops": ["raw"],
                "allowed_fields": ["close", "volume"],
                "preferred_combines": ["rank"],
                "block_count": [1, 1],
            },
            "prototype_genome": prototype.to_dict(),
            "variant_genomes": [variant.to_dict()],
            "ablation_plan": [{"test": "drop leg", "expected": "weaker"}],
            "orthogonality_plan": {
                "nearest_baselines": ["momentum"], "why_not_spanned": "test it"},
            "kill_criteria": ["corr_gate"],
            "search_directions": [
                {"direction": "swap field", "priority": 1, "rationale": "test"}],
        }


def test_planner_creates_exact_half_exploit_half_explore(tmp_path) -> None:
    agent = PlannerAgent(_PlannerClient(), tmp_path / "planner.md", {})
    templates = agent.plan_batch(
        2,
        {"archive_elites": [
            {"factor_id": "parent-a", "genome": _genome("close").to_dict()},
            {"factor_id": "parent-b", "genome": _genome("volume").to_dict()},
        ]},
        mechanisms=4,
        available_fields=("close", "volume"),
    )
    assert [template["research_track"] for template in templates] == [
        "exploit", "exploit", "explore", "explore"]
    assert all(template["parent_factor_ids"] for template in templates[:2])
    assert all(not template["parent_factor_ids"] for template in templates[2:])


def test_first_round_is_explicit_all_explore_bootstrap(tmp_path) -> None:
    agent = PlannerAgent(_PlannerClient(), tmp_path / "planner.md", {})
    templates = agent.plan_batch(
        1, {}, mechanisms=2, available_fields=("close", "volume"))
    assert [template["research_track"] for template in templates] == [
        "explore", "explore"]


def test_duplicate_planner_batch_fails_without_polluting_memory(tmp_path) -> None:
    class DuplicateClient(_PlannerClient):
        def chat_json(self, messages, **kwargs):
            template = super().chat_json(messages, **kwargs)
            template["hypothesis"] = "duplicate"
            return template

    memory = tmp_path / "planner.md"
    agent = PlannerAgent(DuplicateClient(), memory, {})
    with pytest.raises(ValueError, match="重复机制"):
        agent.plan_batch(
            1, {}, mechanisms=2, available_fields=("close", "volume"))
    assert not memory.exists()


def test_planner_gets_one_strict_self_correction_for_invalid_dsl(tmp_path) -> None:
    class CorrectingClient(_PlannerClient):
        calls = 0

        def chat_json(self, messages, **kwargs):
            self.calls += 1
            template = super().chat_json(messages, **kwargs)
            if self.calls == 1:
                template["search_space"]["allowed_ops"] = ["rank"]
            return template

    client = CorrectingClient()
    agent = PlannerAgent(client, tmp_path / "planner.md", {})
    template = agent.plan(
        1, {}, available_fields=("close", "volume"), research_track="explore")
    assert client.calls == 2
    assert template["search_space"]["allowed_ops"] == ("raw",)


def test_component_credit_changes_sampling_and_roundtrips() -> None:
    table = ComponentCreditTable(
        exploration_floor=0.2, learning_rate=0.5, temperature=0.2)
    for _ in range(8):
        table.update("field", "close", 1.0, round_no=2)
        table.update("field", "volume", -1.0, round_no=2)
    probabilities = table.probabilities("field", ("close", "volume"))
    assert probabilities[0] > probabilities[1]
    assert probabilities[1] >= 0.1  # exploration_floor / two choices
    restored = ComponentCreditTable.from_dict(table.to_dict())
    assert restored.to_dict() == table.to_dict()


def test_ga_persists_rng_warm_start_and_credit() -> None:
    search = GeneticSearch(population_size=6, generations=1, seed=9)
    space = normalize_search_space({"search_space": {
        "allowed_ops": ["raw"],
        "allowed_fields": ["close", "volume"],
        "preferred_combines": ["rank"],
        "block_count": [1, 1],
    }})
    search.evolve(
        lambda genomes: [
            1.0 if genome.blocks[0].inputs == ["close"] else -1.0
            for genome in genomes
        ],
        search_space=space,
        seed_genomes=[_genome("close"), _genome("volume")],
        round_no=1,
    )
    state = search.export_state()
    restored = GeneticSearch(population_size=6, generations=1, seed=999)
    restored.load_state(state)
    assert restored.export_state() == state
    assert restored.credit.probabilities("field", ("close", "volume"))[0] > 0.5


def test_ga_discards_platform_confirmed_retire_from_warm_start() -> None:
    rejected = Genome([
        ExpressionBlock("order_book_imbalance", [], {}, "+"),
    ], "zscore")
    retained = Genome([
        ExpressionBlock("ratio", ["bid_volume3", "ask_volume1"], {}, "+"),
    ], "zscore")
    ga = GeneticSearch(population_size=4, generations=1)
    state = ga.export_state()
    state["warm_start"] = [rejected.to_dict(), retained.to_dict()]
    ga.load_state(state)

    ga.discard_warm_start({rejected.fingerprint()})

    assert ga.export_state()["warm_start"] == [retained.to_dict()]


def test_archive_roundtrip_and_candidate_track_quota() -> None:
    runner = RoundRunner.__new__(RoundRunner)
    runner._recorded_ids = set()
    runner._genomes = {}
    rng = np.random.default_rng(5)
    dates = pd.bdate_range("2024-01-02", periods=60)
    rows = [(d, i) for d in dates for i in range(1, 21)]
    df = pd.DataFrame(rows, columns=["date", "instrument"])
    df["close"] = 10 + rng.standard_normal(len(df)).cumsum() % 30
    df["volume"] = rng.integers(1000, 50000, len(df)).astype("float32")
    runner.data = {"df": df, "ret": df[["date", "instrument", "close"]]}
    families = []
    for index, track in enumerate(("exploit", "exploit", "explore", "explore")):
        archive = MapElitesArchive(n_bins=6, limit=20)
        results = []
        for item in range(4):
            code = index * 4 + item
            genome = Genome([
                ExpressionBlock(
                    "raw", ["close" if code & 1 else "volume"], {},
                    "+" if code & 2 else "-"),
                ExpressionBlock(
                    "raw", ["close" if code & 4 else "volume"], {},
                    "+" if code & 8 else "-"),
            ], "rank")
            factor_id = genome.fingerprint()
            runner._genomes[factor_id] = genome
            score = float(100 - index * 10 - item)
            archive.add(factor_id, {
                "rank_ic_ir": score / 100,
                "max_corr_refset": item / 10,
                "complexity": len(genome.blocks),
            }, score, payload={"genome": genome.to_dict()})
            results.append((genome, score))
        families.append({
            "slot": index + 1,
            "template": {"research_track": track},
            "archive": archive,
            "results": results,
        })
    candidates = runner._select_family_candidates(families, 8)
    assert len(candidates) == 8
    assert sum(item[2]["research_track"] == "exploit" for item in candidates) == 4
    assert sum(item[2]["research_track"] == "explore" for item in candidates) == 4
    restored = MapElitesArchive.from_dict(families[0]["archive"].to_dict())
    assert restored.best_of_cells() == families[0]["archive"].best_of_cells()
