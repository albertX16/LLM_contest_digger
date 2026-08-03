"""驱动一轮完整的自动化投研。

流程（严格模式：已启用组件失败即中止，不做静默降级）：
1. planner agent（LLM）→ exploit/explore 各半的多个独立机制模板。
2. 每个机制拥有独立搜索空间和候选配额；GA 的组件信用跨机制、跨轮持久化。
3. 本地评估：expr.py 求值 + quick_fitness 粗筛 + score_factor 完整评分。
4. ledger 记录每个候选（append-only）。
5. summarizer agent（LLM）总结本轮教训；已启用时失败即中止。
6. 幸存者进入平台评估队列（CDP 上传 + 执行 + 读取 + 回写 ledger）。
"""

from __future__ import annotations

import os
import json
import hashlib
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# 用户指示（2026-08-03）：本地自动化改用 2024 年 1 分钟数据挖掘因子。
# 显式声明自动化合法窗口，ledger 校验器才会放行 2024（仓库其他流程默认仍禁止）。
os.environ.setdefault("AUTOMATION_ALLOWED_WINDOW_YEARS", "2024")

sys.path.insert(0, str(
    Path(__file__).resolve().parents[2]
    / "bigalpha2026_main_src/bigalpha2026-main/mining"
))
from ledger import append as ledger_append  # noqa: E402

from automation.agents.llm_client import LLMClient
from automation.agents.planner import PlannerAgent
from automation.agents.summarizer import SummarizerAgent
from automation.evaluate.bproxy import quick_fitness
from automation.evaluate.expr import eval_genome
from automation.evaluate.score import score_candidate, score_config_from_dict
from automation.search.ga import GeneticSearch
from automation.search.genome import (
    RAW_FIELDS,
    Genome,
    constrain_to_columns,
    normalize_search_space,
)
from automation.search.map_elites import MapElitesArchive
from automation.panel.fetch import to_daily_factor, daily_forward_return
from automation.loop.platform_eval import PlatformEvaluator
from automation.loop.rewrite_queue import write_spec

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class RoundRunner:
    """一轮搜索的编排器。"""

    def __init__(
        self,
        config: dict,
        client: LLMClient | None,
        data: dict[str, pd.DataFrame],
        refset: dict[str, pd.DataFrame] | None = None,
        exposures: dict[str, pd.DataFrame] | None = None,
        run_dir: Path | None = None,
    ) -> None:
        self.config = config
        self.client = client
        self.data = data  # {"df": long bar panel, "ret": (date,instrument,ret_fwd)}
        if not refset:
            raise ValueError("严格模式要求非空 RefSet")
        if not exposures:
            raise ValueError("严格模式要求非空风险 exposures")
        self.refset = refset
        self.exposures = exposures
        self.run_dir = run_dir or Path(config["loop"]["run_dir"])
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.run_dir / "ledger.jsonl"
        planner_context = {
            **config.get("evaluate", {}),
            "platform_score_target": config.get("search", {}).get(
                "platform_score_target", 0.85),
            "platform_score_stretch": config.get("search", {}).get(
                "platform_score_stretch", 0.90),
        }
        self.planner = (PlannerAgent(client, config["llm"]["memory"]["planner"],
                                     planner_context)
                        if client is not None else None)
        self.summarizer = (SummarizerAgent(client, config["llm"]["memory"]["summarizer"])
                           if client is not None else None)
        ga_kwargs = {
            k: config["search"][k]
            for k in (
                "population_size", "generations", "elite_frac",
                "mutation_rate", "crossover_rate", "tournament_size", "seed",
                "exploration_floor", "credit_learning_rate", "credit_temperature",
            )
            if k in config["search"]
        }
        self.ga = GeneticSearch(**ga_kwargs)
        self.platform = PlatformEvaluator()
        self.archive = MapElitesArchive(
            n_bins=int(config["search"].get("map_elites_bins", 6)),
            limit=int(config["search"].get("archive_limit", 200)),
        )
        self._genomes: dict[str, Genome] = {}
        self.score_config = score_config_from_dict(config.get("evaluate"))
        self._uploaded_ids: set[str] = set()
        self._recorded_ids: set[str] = set()
        self._platform_config = config.get("loop", {}).get("platform", {})
        self._last_diagnostics: dict = {}
        self.last_completed_round = 0
        self._platform_feedback: list[dict] = []
        self._platform_feedback_objective: dict = {}
        self._applied_feedback_digest = ""
        self._leader_sequence: dict = {"schema_version": 1, "leaders": []}
        self._combination_research: dict = {"schema_version": 1}
        self._records_by_id: dict[str, dict] = {}
        self.state_path = self.run_dir / "search_state.json"
        if self.ledger_path.exists():
            for line in self.ledger_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    record = json.loads(line)
                    factor_id = record.get("factor_id")
                    if factor_id:
                        self._recorded_ids.add(str(factor_id))
                        self._records_by_id[str(factor_id)] = record
                    raw_genome = record.get("genome")
                    if factor_id and raw_genome:
                        self._genomes[str(factor_id)] = Genome.from_dict(raw_genome)
        if self.state_path.exists():
            self._load_state()
        else:
            self._restore_legacy_state()
        self._load_platform_feedback()
        self._load_leader_sequence()
        self._load_combination_research()

    def run(self, round_no: int, diagnostics: dict | None = None) -> dict:
        """执行一轮，返回汇总。"""
        expected_round = self.last_completed_round + 1
        if round_no != expected_round:
            raise ValueError(
                f"轮次必须连续：持久化状态期望 round_no={expected_round}，"
                f"收到 {round_no}")
        t0 = time.time()
        diagnostics = dict(
            diagnostics if diagnostics is not None else self._last_diagnostics)
        diagnostics["archive_elites"] = self._archive_elites()
        diagnostics["component_credit"] = self.ga.credit.top(20)
        diagnostics["platform_feedback"] = self._platform_feedback
        diagnostics["platform_objective"] = self._platform_feedback_objective
        diagnostics["leader_factor_sequence"] = self._leader_sequence_view()
        diagnostics["combination_mode"] = "single_factor_mining"
        diagnostics["combination_guardrails"] = self._combination_research.get(
            "ordinary_round_guardrails", [])

        # 1. planner：每个模板是独立机制；有历史时 exploit/explore 严格各半。
        templates: list[dict | None]
        if self.planner is not None:
            actual_fields = tuple(
                field for field in RAW_FIELDS if field in self.data["df"].columns
            )
            mechanisms = int(self.config["search"].get("mechanisms_per_round", 4))
            templates = self.planner.plan_batch(
                round_no,
                diagnostics,
                mechanisms=mechanisms,
                available_fields=actual_fields,
            )
        else:
            # Explicit LLM-off mode remains one unconstrained programmatic search.
            templates = [None]

        # 2. 每个机制独立 GA 搜索 + 3. 本地评估。
        self._fit_details: dict[str, dict] = {}
        self._full_scores: dict[str, dict] = {}
        template_by_fp: dict[str, dict | None] = {}

        def fitness(genomes: list[Genome]) -> list[float]:
            scores = []
            for g in genomes:
                detail = self._local_fitness(g)
                self._fit_details[g.fingerprint()] = detail
                scores.append(float(detail["fitness"]))
            return scores

        family_runs: list[dict] = []
        round_ranked: list[tuple[Genome, float]] = []
        for mechanism_slot, template in enumerate(templates, start=1):
            if template is not None:
                template["mechanism_slot"] = mechanism_slot
            search_space = constrain_to_columns(
                normalize_search_space(template),
                self.data["df"].columns,
                reject_missing_fields=template is not None,
            )
            seed_genomes: list[Genome] = []
            if template is not None:
                seed_genomes.extend([
                    Genome.from_dict(template["prototype_genome"]),
                    *[Genome.from_dict(raw) for raw in template["variant_genomes"]],
                ])
                for parent_id in template["parent_factor_ids"]:
                    parent = self._genomes.get(parent_id)
                    if parent is None:
                        raise RuntimeError(
                            f"exploit 父因子 {parent_id} 在持久化 genome 中不存在")
                    seed_genomes.append(Genome.from_dict(parent.to_dict()))
            results = self.ga.evolve(
                fitness,
                search_space=search_space,
                seed_genomes=seed_genomes or None,
                # A mechanism may see historical evidence through its assigned
                # parent, archive diagnostics and component credit. It must not
                # inherit a genome produced by an earlier slot in this round.
                include_persistent_warm_start=False,
                update_persistent_warm_start=False,
                round_no=round_no,
                on_generation=lambda generation, ranked, slot=mechanism_slot: log.info(
                    "round %d mechanism %d gen %d best=%.4f",
                    round_no, slot, generation, ranked[0][1],
                ),
            )
            round_ranked.extend(results)
            family_archive = MapElitesArchive(
                n_bins=int(self.config["search"].get("map_elites_bins", 6)),
                limit=int(self.config["search"].get("archive_limit", 200)),
            )
            for genome, score in results:
                fingerprint = genome.fingerprint()
                self._genomes[fingerprint] = Genome.from_dict(genome.to_dict())
                template_by_fp.setdefault(fingerprint, template)
                detail = self._fit_details.get(fingerprint, {})
                feature = {
                    "rank_ic_ir": float(detail.get("rank_ic_ir", 0.0)),
                    "max_corr_refset": float(detail.get("max_corr_refset", 1.0)),
                    "complexity": float(len(genome.blocks)),
                }
                payload = {
                    "genome": genome.to_dict(),
                    "research_track": (template or {}).get("research_track", "ga-only"),
                    "hypothesis": (template or {}).get("hypothesis", "GA 无模板搜索"),
                }
                self.archive.add(
                    fingerprint, feature, float(score), payload=payload)
                family_archive.add(
                    fingerprint, feature, float(score), payload=payload)
            family_runs.append({
                "slot": mechanism_slot,
                "template": template,
                "results": results,
                "archive": family_archive,
            })

        candidate_limit = int(self.config["search"].get("candidates_per_round", 10))
        if candidate_limit < len(family_runs):
            raise ValueError(
                "candidates_per_round 必须不少于 mechanisms_per_round，"
                "否则无法保证每个机制至少一个完整评分候选")
        candidates = self._select_family_candidates(family_runs, candidate_limit)
        if not candidates:
            raise RuntimeError("本轮所有机制都没有产生未记录候选")

        # 幸存者走 repo 完整三级联评分
        for genome, _fit, _template in candidates:
            detail = self._fit_details.get(genome.fingerprint(), {})
            if detail.get("fitness", 0) <= 0:
                self._full_scores[genome.fingerprint()] = {
                    "passed": False,
                    "reject_reason": "quick_fitness 粗筛未通过（fitness<=0 或全 NaN）",
                }
                continue
            long_panel = self._factor_long(genome)
            qv = score_candidate(
                genome.fingerprint(),
                long_panel,
                self.data["ret"],
                refset=self.refset,
                exposures=self.exposures,
                config=self.score_config,
            )
            self._validate_score_contract(qv)
            self._apply_confirm_window_gate(qv, long_panel)
            risk_mode = self.config.get("evaluate", {}).get(
                "exposure_mode", "unspecified")
            qv["preprocessing"]["risk_control_mode"] = risk_mode
            qv["preprocessing"]["official_barra"] = risk_mode == "official_file"
            self._full_scores[genome.fingerprint()] = qv

        # 4. ledger：写所有候选（含淘汰）
        records = []
        for genome, fit, template in candidates:
            rec = self._to_ledger_record(genome, fit, round_no, template)
            records.append(rec)
            self._append_ledger(rec)

        # 5. summarizer：总结（失败则机器总结）
        summary = None
        if self.summarizer is not None:
            summary = self.summarizer.summarize(records)

        self._last_diagnostics = self._next_diagnostics(records, summary)
        self._update_leader_sequence(round_no, records)
        # Full cascade outcomes are later and stronger evidence than the GA's
        # cheap screen, so feed them backward into component credit before save.
        record_ranked = sorted(
            ((self._genomes[record["factor_id"]], self._record_learning_score(record))
             for record in records),
            key=lambda item: item[1],
            reverse=True,
        )
        self.ga.credit.update_genomes(record_ranked, round_no=round_no)
        # Commit seeds only after every mechanism has completed. They become
        # next-round state and can never leak from slot N into slot N+1.
        self.ga.set_warm_start_from_ranked(round_ranked)
        self._save_state(round_no)

        # 6. 只生成因子规格队列。提交 main/notebook 必须由交互式 Agent
        # 参照平台真实模板重写和复核；自动流程不再生成或上传提交代码。
        platform_results: list[dict] = []
        prepared_artifacts: list[dict] = []
        if self._platform_config.get("auto_upload", False):
            raise ValueError(
                "agent_rewrite_queue 模式禁止自动上传；请由交互式 Agent 批量重写后上传")
        max_artifacts = int(self._platform_config.get(
            "max_artifacts_per_round", len(records)))

        artifact_count = 0
        artifact_dir = (
            self.run_dir / "agent_rewrite_queue" / f"round_{round_no:03d}")
        artifact_dir.mkdir(parents=True, exist_ok=True)
        for rec in records:
            if rec["verdict"] != "keep" or artifact_count >= max_artifacts:
                continue
            fid = rec["factor_id"]
            genome = self._genomes[fid]
            local_path, _ = write_spec(
                artifact_dir,
                rec,
                round_no,
                selection_reason="local_cascade_keep",
            )
            prepared = {
                "factor_id": fid,
                "factor_spec_path": str(local_path),
                "expression": genome.to_expression(),
                "rewrite_status": "pending_agent_rewrite",
            }
            prepared_artifacts.append(prepared)
            artifact_count += 1

        queue_manifest = artifact_dir / "manifest.json"
        queue_manifest.write_text(json.dumps({
            "schema_version": 1,
            "round_no": round_no,
            "artifact_mode": "pending_agent_rewrite",
            "automatic_notebook_generation": False,
            "automatic_upload": False,
            "factors": prepared_artifacts,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        wall = time.time() - t0
        result = {
            "round_no": round_no,
            "wall_seconds": round(wall, 1),
            "n_candidates": len(candidates),
            "n_kept": sum(1 for r in records if r["verdict"] == "keep"),
            "n_platform_eval": len(platform_results),
            "n_prepared": len(prepared_artifacts),
            "mechanisms": [
                {
                    "slot": index,
                    "research_track": (template or {}).get("research_track", "ga-only"),
                    "hypothesis": (template or {}).get("hypothesis", "GA 无模板搜索"),
                    "parent_factor_ids": (template or {}).get("parent_factor_ids", []),
                }
                for index, template in enumerate(templates, start=1)
            ],
            "candidate_allocation": self._candidate_allocation(records),
            "component_credit_top": self.ga.credit.top(20),
            "archive_cells": len(self.archive.cells),
            "summary": summary,
            "platform_results": platform_results,
            "prepared_artifacts": prepared_artifacts,
            "agent_rewrite_manifest": str(queue_manifest),
            "next_diagnostics": self._last_diagnostics,
            "ts": _now(),
        }
        (self.run_dir / "round_summary.jsonl").open("a", encoding="utf-8").write(
            json.dumps(result, ensure_ascii=False, default=str) + "\n")

        return result

    def _select_family_candidates(
        self, family_runs: list[dict], candidate_limit: int,
    ) -> list[tuple[Genome, dict, dict | None]]:
        """Reserve a fair quota for every mechanism and both research tracks."""
        tracks = [
            (family["template"] or {}).get("research_track", "ga-only")
            for family in family_runs
        ]
        groups: dict[str, list[int]] = {}
        for index, track in enumerate(tracks):
            groups.setdefault(track, []).append(index)
        if set(groups) == {"exploit", "explore"}:
            track_limits = {
                "exploit": candidate_limit // 2,
                "explore": candidate_limit - candidate_limit // 2,
            }
        else:
            track_limits = {next(iter(groups)): candidate_limit}

        quotas = [0] * len(family_runs)
        for track, indices in groups.items():
            total = track_limits[track]
            base, remainder = divmod(total, len(indices))
            for position, index in enumerate(indices):
                quotas[index] = base + int(position < remainder)

        selected: list[tuple[Genome, dict, dict | None]] = []
        selected_ids: set[str] = set()
        config = getattr(self, "config", {}) or {}
        corr_max = float(config.get("evaluate", {}).get(
            "same_round_corr_max", 0.6))
        vector_cache: dict[str, pd.Series] = {}

        def factor_vector(genome: Genome) -> pd.Series:
            fingerprint = genome.fingerprint()
            if fingerprint not in vector_cache:
                panel = to_daily_factor(
                    eval_genome(genome, self.data["df"]), self.data["df"])
                wide = panel.pivot(
                    index="date", columns="instrument", values="factor")
                vector_cache[fingerprint] = wide.stack().rank()
            return vector_cache[fingerprint]

        def too_correlated(genome: Genome) -> bool:
            if corr_max <= 0 or not selected_ids:
                return False
            vector = factor_vector(genome)
            for other_id in selected_ids:
                other = self._genomes[other_id]
                other_vector = factor_vector(other)
                index = vector.index.intersection(other_vector.index)
                if len(index) < 30:
                    return True  # 样本不足视为同质，避免进入候选
                corr = float(vector.loc[index].corr(other_vector.loc[index]))
                if corr > corr_max:
                    return True
            return False

        for index, family in enumerate(family_runs):
            ordered_ids: list[tuple[str, float]] = [
                (str(elite["id"]), float(elite["score"]))
                for elite in family["archive"].best_of_cells()
            ]
            ordered_ids.extend(
                (genome.fingerprint(), float(score))
                for genome, score in family["results"]
            )
            taken = 0
            queue: list[tuple[str, float]] = []
            for factor_id, score in ordered_ids:
                if (factor_id in self._recorded_ids
                        or factor_id in selected_ids):
                    continue
                candidate = self._genomes.get(factor_id)
                if candidate is None:
                    raise RuntimeError(
                        f"机制 {family['slot']} 候选 {factor_id} 缺少 genome payload")
                queue.append((factor_id, score))
            # 多样性优先：同一轮不同机制之间日频因子相关性超过上限则跳过，
            # 保证每个机制都贡献内容上不同的候选（防 R4 同族复制重演）。
            for factor_id, score in queue:
                if taken >= quotas[index]:
                    break
                genome = self._genomes[factor_id]
                if selected_ids and too_correlated(genome):
                    continue
                selected.append((genome, {"fitness": score}, family["template"]))
                selected_ids.add(factor_id)
                taken += 1
            # 兜底：相关性约束不得破坏机制配额，剩余名额由本族最优未选候选补足。
            if taken < quotas[index]:
                for factor_id, score in queue:
                    if taken >= quotas[index]:
                        break
                    if factor_id in selected_ids:
                        continue
                    genome = self._genomes[factor_id]
                    selected.append(
                        (genome, {"fitness": score}, family["template"]))
                    selected_ids.add(factor_id)
                    taken += 1
            if taken < quotas[index]:
                raise RuntimeError(
                    f"机制 {family['slot']} 只产生 {taken} 个未记录候选，"
                    f"低于预留配额 {quotas[index]}；严格模式不跨机制挪用配额")
        return selected

    @staticmethod
    def _record_learning_score(record: dict) -> float:
        metrics = record.get("metrics", {})
        base = float(metrics.get("fitness", 0.0) or 0.0)
        neutral_t = float(metrics.get("neutralized_rank_ic_tstat", 0.0) or 0.0)
        crowding = float(metrics.get("max_corr_refset", 1.0) or 0.0)
        keep_bonus = 1000.0 if record.get("verdict") == "keep" else 0.0
        return keep_bonus + base + neutral_t - crowding

    @staticmethod
    def _validate_score_contract(qv: dict) -> None:
        """Allow a stage-1 candidate rejection, never an unneutralized score.

        The scorer intentionally checks the factor-panel contract before it can
        run risk residualization.  Such a candidate has no score and must be
        retired as a contract error.  Any candidate that reaches stage 2/3
        without neutralization is an infrastructure/configuration breach and
        remains fatal.
        """
        stage = int(qv.get("stage_reached", 0) or 0)
        if stage == 1 and not qv.get("passed"):
            return
        if not qv.get("preprocessing", {}).get("neutralized"):
            raise RuntimeError("进入信号评分的候选未执行风险残差化，严格模式中止")

    def _apply_confirm_window_gate(self, qv: dict, long_panel: pd.DataFrame) -> None:
        """搜索/确认窗口拆分：确认段（下半年）RankIC t 值必须达标。

        防止只在搜索段成立的过拟合信号进入候选池。t 值在残差化前的日频
        因子与 forward return 上计算（与完整三级联互补，不替代官方 Barra）。
        """
        confirm_split = self.config.get("evaluate", {}).get("confirm_split")
        t_min = float(self.config.get("evaluate", {}).get(
            "confirm_t_min", 0.0) or 0.0)
        if not confirm_split or t_min <= 0:
            qv["confirm_window_t"] = None
            qv["confirm_window_n_days"] = None
            return
        start_ts = pd.Timestamp(confirm_split)
        panel = long_panel[pd.to_datetime(long_panel["date"]) >= start_ts]
        ret = self.data["ret"]
        ret = ret[pd.to_datetime(ret["date"]) >= start_ts]
        if panel.empty or len(panel) < 30 or ret.empty:
            qv["passed"] = False
            qv["reject_reason"] = "confirm_window_insufficient_data"
            qv["confirm_window_t"] = None
            qv["confirm_window_n_days"] = 0
            return
        fw = panel.pivot(index="date", columns="instrument", values="factor")
        rw = ret.pivot(index="date", columns="instrument", values="ret_fwd")
        common = fw.index.intersection(rw.index)
        if len(common) < 30:
            qv["passed"] = False
            qv["reject_reason"] = "confirm_window_insufficient_data"
            qv["confirm_window_t"] = None
            qv["confirm_window_n_days"] = int(len(common))
            return
        rank_ic = (
            fw.loc[common].rank(axis=1).corrwith(rw.loc[common], axis=1)
        ).dropna()
        if len(rank_ic) < 30:
            qv["passed"] = False
            qv["reject_reason"] = "confirm_window_insufficient_data"
            qv["confirm_window_t"] = None
            qv["confirm_window_n_days"] = int(len(rank_ic))
            return
        t_stat = float(rank_ic.mean() / (rank_ic.std(ddof=1) + 1e-12)
                       * (len(rank_ic) ** 0.5))
        qv["confirm_window_t"] = t_stat
        qv["confirm_window_n_days"] = int(len(rank_ic))
        if abs(t_stat) < t_min:
            qv["passed"] = False
            qv["reject_reason"] = "confirm_window_gate_failed"

    @staticmethod
    def _candidate_allocation(records: list[dict]) -> dict[str, int]:
        allocation: dict[str, int] = {}
        for record in records:
            track = str(record.get("research_track", "ga-only"))
            allocation[track] = allocation.get(track, 0) + 1
        return allocation

    @staticmethod
    def _payload_genome(payload: dict | None) -> Genome | None:
        if not payload:
            return None
        raw = payload.get("genome", payload)
        return Genome.from_dict(raw) if isinstance(raw, dict) else None

    def _archive_elites(self) -> list[dict]:
        rows = []
        feedback_by_id = {
            str(item["factor_id"]): item for item in self._platform_feedback
        }
        for elite in self.archive.best_of_cells():
            factor_id = str(elite["id"])
            feedback = feedback_by_id.get(factor_id) or {}
            if feedback.get("platform_decision") == "confirmed_retire":
                continue
            genome = self._genomes.get(factor_id) or self._payload_genome(
                elite.get("payload"))
            if genome is None:
                raise RuntimeError(f"archive elite {factor_id} 缺少可恢复 genome")
            record = self._records_by_id.get(factor_id, {})
            payload = elite.get("payload") or {}
            rows.append({
                "factor_id": factor_id,
                "archive_score": float(elite["score"]),
                "archive_feature": elite.get("feature", {}),
                "verdict": record.get("verdict", "quick-screen-only"),
                "metrics": record.get("metrics", {}),
                "hypothesis": record.get(
                    "hypothesis", payload.get("hypothesis", "unknown")),
                "research_track": record.get(
                    "research_track", payload.get("research_track", "unknown")),
                "genome": genome.to_dict(),
                "platform_feedback": feedback_by_id.get(factor_id),
            })
        present = {row["factor_id"] for row in rows}
        for factor_id, feedback in feedback_by_id.items():
            if factor_id in present:
                continue
            if feedback.get("platform_decision") == "confirmed_retire":
                continue
            genome = self._genomes[factor_id]
            record = self._records_by_id.get(factor_id, {})
            metrics = record.get("metrics", {})
            rows.append({
                "factor_id": factor_id,
                "archive_score": float(metrics.get("fitness", 0.0) or 0.0),
                "archive_feature": {
                    "rank_ic_ir": metrics.get("rank_ic_ir", 0.0),
                    "max_corr_refset": metrics.get("max_corr_refset", 1.0),
                    "complexity": len(genome.blocks),
                },
                "verdict": record.get("verdict", "historical"),
                "metrics": metrics,
                "hypothesis": record.get("hypothesis", "historical platform feedback"),
                "research_track": record.get("research_track", "legacy"),
                "genome": genome.to_dict(),
                "platform_feedback": feedback,
            })
        tier_priority = {"leader": 3, "middle": 2, "laggard": 1}
        rows.sort(
            key=lambda row: (
                tier_priority.get(
                    (row.get("platform_feedback") or {}).get("tier"), 0),
                -float((row.get("platform_feedback") or {}).get(
                    "ordinal_rank", 999)),
                row["verdict"] == "keep",
                row["archive_score"],
            ),
            reverse=True,
        )
        mechanisms = int(self.config["search"].get("mechanisms_per_round", 4))
        return rows[:max(8, mechanisms * 3)]

    def _save_state(self, round_no: int) -> None:
        state = {
            "schema_version": 1,
            "last_completed_round": int(round_no),
            "last_diagnostics": self._last_diagnostics,
            "archive": self.archive.to_dict(),
            "ga": self.ga.export_state(),
            "saved_at": _now(),
            "applied_feedback_digest": self._applied_feedback_digest,
        }
        temp_path = self.state_path.with_suffix(".json.tmp")
        temp_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        credit_path = self.run_dir / "component_credit.csv"
        credit_temp = credit_path.with_suffix(".csv.tmp")
        pd.DataFrame(self.ga.credit.top(1_000_000)).to_csv(
            credit_temp, index=False)
        archive_path = self.run_dir / "archive_elites.json"
        archive_temp = archive_path.with_suffix(".json.tmp")
        archive_temp.write_text(
            json.dumps(self._archive_elites(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # Human-readable mirrors land first; search_state is the commit marker
        # and is replaced last so a mirror-write failure cannot advance a round.
        credit_temp.replace(credit_path)
        archive_temp.replace(archive_path)
        temp_path.replace(self.state_path)
        self.last_completed_round = int(round_no)

    def _load_state(self) -> None:
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        required = {
            "schema_version", "last_completed_round", "last_diagnostics",
            "archive", "ga",
        }
        missing = sorted(required.difference(state))
        if missing:
            raise ValueError(f"search_state.json 缺字段: {missing}")
        if state["schema_version"] != 1:
            raise ValueError(
                f"不支持的 search_state schema_version={state['schema_version']}")
        self.archive = MapElitesArchive.from_dict(state["archive"])
        self.ga.load_state(state["ga"])
        self._last_diagnostics = dict(state["last_diagnostics"])
        self.last_completed_round = int(state["last_completed_round"])
        self._applied_feedback_digest = str(
            state.get("applied_feedback_digest", ""))
        for elite in self.archive.best_of_cells():
            genome = self._payload_genome(elite.get("payload"))
            if genome is None:
                raise RuntimeError(f"archive elite {elite['id']} 无法恢复")
            self._genomes[str(elite["id"])] = genome

    def _load_platform_feedback(self) -> None:
        feedback_file = self.config.get("search", {}).get("platform_feedback_file")
        if not feedback_file:
            return
        path = Path(feedback_file)
        if not path.exists():
            raise FileNotFoundError(f"配置的平台反馈文件不存在: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        factors = raw.get("factors")
        if not isinstance(factors, list) or not factors:
            raise ValueError("platform_feedback.json 必须包含非空 factors")
        allowed_precision = {"exact", "approximate", "unknown"}
        allowed_tiers = {"leader", "middle", "laggard"}
        missing_ids = {
            str(item.get("factor_id", "")) for item in factors
            if str(item.get("factor_id", "")) not in self._genomes
        }
        if missing_ids:
            source_dir = Path(str(raw.get("source_run_dir", "")))
            source_ledger = source_dir / "ledger.jsonl"
            if not source_ledger.exists():
                raise FileNotFoundError(
                    f"平台反馈缺少历史 genome，且 source ledger 不存在: {source_ledger}")
            for line in source_ledger.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                factor_id = str(record.get("factor_id", ""))
                if factor_id in missing_ids and record.get("genome"):
                    self._genomes[factor_id] = Genome.from_dict(record["genome"])
                    self._records_by_id[factor_id] = record
            unresolved = sorted(missing_ids.difference(self._genomes))
            if unresolved:
                raise ValueError(f"source ledger 仍缺少平台反馈 genome: {unresolved}")
        for item in factors:
            factor_id = str(item.get("factor_id", ""))
            if factor_id not in self._genomes:
                raise ValueError(f"平台反馈 factor_id 不在历史 genome 中: {factor_id}")
            if item.get("precision") not in allowed_precision:
                raise ValueError(f"平台反馈 precision 非法: {item.get('precision')}")
            if item.get("tier") not in allowed_tiers:
                raise ValueError(f"平台反馈 tier 非法: {item.get('tier')}")
            score = item.get("reported_score")
            if item["precision"] == "unknown" and score is not None:
                raise ValueError("unknown 平台反馈不得带伪造分数")
            if item["precision"] != "unknown" and not isinstance(score, (int, float)):
                raise ValueError("exact/approximate 平台反馈必须带数值")
        confirmed_retired = {
            str(item["factor_id"]) for item in factors
            if item.get("platform_decision") == "confirmed_retire"
        }
        self.ga.discard_warm_start(confirmed_retired)
        canonical = json.dumps(raw, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        self._platform_feedback = factors
        self._platform_feedback_objective = dict(raw.get("objective") or {})
        for item in factors:
            record = self._records_by_id.get(str(item["factor_id"]))
            if record is not None:
                record["platform_feedback"] = item
        if digest == self._applied_feedback_digest:
            return
        ranked = [
            (self._genomes[str(item["factor_id"])], -float(item["ordinal_rank"]))
            for item in factors
            if item.get("reported_score") is not None
            and item.get("ordinal_rank") is not None
        ]
        self.ga.credit.update_genomes(ranked, round_no=self.last_completed_round)
        self._applied_feedback_digest = digest

    def _load_leader_sequence(self) -> None:
        sequence_file = self.config.get("search", {}).get("leader_sequence_file")
        if not sequence_file:
            return
        path = Path(sequence_file)
        if not path.exists():
            raise FileNotFoundError(f"领先因子序列不存在: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != 1 or not isinstance(raw.get("leaders"), list):
            raise ValueError("leader_factor_sequence schema 非法")
        self._leader_sequence = raw

    def _load_combination_research(self) -> None:
        research_file = self.config.get("search", {}).get(
            "combination_research_file")
        if not research_file:
            return
        path = Path(research_file)
        if not path.exists():
            raise FileNotFoundError(f"因子组合研究记忆不存在: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if (raw.get("schema_version") != 1
                or not isinstance(raw.get("ordinary_round_guardrails"), list)
                or not isinstance(raw.get("specialized_combination_task"), dict)):
            raise ValueError("factor_combination_research schema 非法")
        self._combination_research = raw

    def _leader_sequence_view(self) -> list[dict]:
        leaders = list(self._leader_sequence.get("leaders", []))
        verified = [
            item for item in leaders
            if not str(item.get("evidence_scope", "")).startswith("local_")
        ]
        local = [
            item for item in leaders
            if str(item.get("evidence_scope", "")).startswith("local_")
        ]
        local.sort(key=lambda item: int(item.get("round_no", 0)), reverse=True)
        return verified + local[:12]

    def _update_leader_sequence(self, round_no: int, records: list[dict]) -> None:
        sequence_file = self.config.get("search", {}).get("leader_sequence_file")
        if not sequence_file:
            return
        by_mechanism: dict[int, list[dict]] = {}
        for record in records:
            slot = record.get("mechanism_slot")
            if isinstance(slot, int):
                by_mechanism.setdefault(slot, []).append(record)
        existing = {
            str(item.get("factor_id"))
            for item in self._leader_sequence.get("leaders", [])
        }
        for slot, values in sorted(by_mechanism.items()):
            leader = max(values, key=self._record_learning_score)
            if leader["factor_id"] in existing:
                continue
            self._leader_sequence["leaders"].append({
                "factor_id": leader["factor_id"],
                "display_name": f"Round {round_no} mechanism {slot} local leader",
                "evidence_scope": "local_unconfirmed",
                "priority": "round_leader",
                "round_no": round_no,
                "mechanism_slot": slot,
                "research_track": leader.get("research_track"),
                "verdict": leader.get("verdict"),
                "metrics": leader.get("metrics", {}),
                "mechanism": leader.get("hypothesis"),
                "genome_expression": leader.get("genome_expression"),
            })
        path = Path(sequence_file)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(
            self._leader_sequence, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)

    def _restore_legacy_state(self) -> None:
        """One-time migration from the append-only ledger into the new state."""
        ranked: list[tuple[Genome, float]] = []
        for factor_id, record in self._records_by_id.items():
            genome = self._genomes.get(factor_id)
            if genome is None:
                continue
            metrics = record.get("metrics", {})
            score = float(metrics.get("fitness", 0.0) or 0.0)
            feature = {
                "rank_ic_ir": float(metrics.get("rank_ic_ir", 0.0) or 0.0),
                "max_corr_refset": float(metrics.get("max_corr_refset", 1.0) or 1.0),
                "complexity": float(len(genome.blocks)),
            }
            self.archive.add(
                factor_id,
                feature,
                score,
                payload={
                    "genome": genome.to_dict(),
                    "research_track": record.get("research_track", "legacy"),
                    "hypothesis": record.get("hypothesis", "legacy ledger"),
                },
            )
            ranked.append((genome, self._record_learning_score(record)))
        if ranked:
            self.ga.credit.update_genomes(ranked, round_no=0)
        summary_path = self.run_dir / "round_summary.jsonl"
        if summary_path.exists():
            lines = [line for line in summary_path.read_text(
                encoding="utf-8").splitlines() if line.strip()]
            if lines:
                latest = json.loads(lines[-1])
                self._last_diagnostics = dict(latest.get("next_diagnostics") or {})
                self.last_completed_round = int(latest.get("round_no", 0) or 0)
        if self.last_completed_round == 0:
            self.last_completed_round = max(
                (int(record.get("round_no", 0) or 0)
                 for record in self._records_by_id.values()),
                default=0,
            )

    @staticmethod
    def _next_diagnostics(records: list[dict], summary: dict | None) -> dict:
        """Condense one round into the evidence passed to the next planner."""
        kept = [record for record in records if record.get("verdict") == "keep"]
        retired = [record for record in records if record.get("verdict") != "keep"]
        return {
            "candidate_count": len(records),
            "kept_count": len(kept),
            "best_kept": sorted(
                ({"factor_id": record["factor_id"], "metrics": record.get("metrics", {}),
                  "research_track": record.get("research_track"),
                  "hypothesis": record.get("hypothesis")}
                 for record in kept),
                key=lambda item: item["metrics"].get("fitness", float("-inf")),
                reverse=True,
            )[:5],
            "best_attempts": sorted(
                ({"factor_id": record["factor_id"], "metrics": record.get("metrics", {}),
                  "verdict": record.get("verdict"),
                  "research_track": record.get("research_track"),
                  "hypothesis": record.get("hypothesis")}
                 for record in records),
                key=lambda item: item["metrics"].get("fitness", float("-inf")),
                reverse=True,
            )[:10],
            "retirement_reasons": [record.get("kill_reason") for record in retired[:10]],
            "summarizer_advice": summary or {},
        }

    def _local_fitness(self, g: Genome) -> dict:
        """求值 + 粗筛，返回 quick_fitness 完整指标 dict。"""
        df = self.data["df"]
        factor_30m = eval_genome(g, df)
        if factor_30m.isna().all():
            return {"rank_ic": 0.0, "rank_ic_ir": 0.0, "max_corr_refset": 0.0, "fitness": -1e9}
        daily_factor = to_daily_factor(factor_30m, df)
        fw = daily_factor.pivot(index="date", columns="instrument", values="factor")
        ret = self.data["ret"]
        rw = ret.pivot(index="date", columns="instrument", values="ret_fwd")
        return quick_fitness(fw, rw, self.refset)

    def _factor_long(self, g: Genome) -> pd.DataFrame:
        """返回用于 score_factor 的日频长表 (date, instrument, factor)。"""
        df = self.data["df"]
        factor_30m = eval_genome(g, df)
        return to_daily_factor(factor_30m, df)

    def _to_ledger_record(self, genome: Genome, fit: dict, round_no: int,
                          template: dict | None) -> dict:
        """生成 ledger 记录，包含完整的 genome 结构以供重现。"""
        detail = self._fit_details.get(genome.fingerprint(), fit)
        qv = self._full_scores.get(genome.fingerprint(), {})
        passed = bool(qv.get("passed"))
        quick_ok = detail.get("fitness", 0) > 0
        verdict = "keep" if (quick_ok and passed) else "retire"
        metrics = {
            "fitness": round(detail.get("fitness", 0), 4),
            "rank_ic": round(detail.get("rank_ic", 0), 4),
            "rank_ic_ir": round(detail.get("rank_ic_ir", 0), 4),
            "rank_ic_tstat": round(detail.get("rank_ic_tstat", 0), 4),
            "max_corr_refset": round(detail.get("max_corr_refset", 0), 4),
        }
        a_score = qv.get("a_score") or {}
        b_proxy = qv.get("b_proxy") or {}
        neutral_ic = a_score.get("rank_ic_mean",
                                 a_score.get("quick_rank_ic_mean"))
        neutral_ir = a_score.get("rank_ic_ir")
        neutral_t = a_score.get("quick_rank_ic_tstat")
        if neutral_t is None and isinstance(neutral_ir, (int, float)):
            n_days = int(a_score.get("n_days", 0) or 0)
            neutral_t = float(neutral_ir) * (n_days ** 0.5)
        if isinstance(neutral_ic, (int, float)):
            metrics["neutralized_rank_ic"] = round(float(neutral_ic), 4)
        if isinstance(neutral_ir, (int, float)):
            metrics["neutralized_rank_ic_ir"] = round(float(neutral_ir), 4)
        if isinstance(neutral_t, (int, float)):
            metrics["neutralized_rank_ic_tstat"] = round(float(neutral_t), 4)
        for k in ("ic_mean", "rank_ic_mean", "rank_ic_ir", "pfs", "rank_stability",
                  "ls_sharpe", "model_score", "kept_fraction"):
            if k in a_score and isinstance(a_score[k], (int, float)):
                metrics[k] = round(float(a_score[k]), 4)
            if k in b_proxy and isinstance(b_proxy[k], (int, float)):
                metrics[k] = round(float(b_proxy[k]), 4)
        if qv.get("confirm_window_t") is not None:
            metrics["confirm_window_t"] = round(
                float(qv["confirm_window_t"]), 4)
            metrics["confirm_window_n_days"] = qv.get("confirm_window_n_days")
        if "max_abs_corr_vs_refset" in b_proxy:
            metrics["max_corr_refset"] = round(float(b_proxy["max_abs_corr_vs_refset"]), 4)
        parent_ids = list((template or {}).get("parent_factor_ids", []))
        parent_id = parent_ids[0] if parent_ids else None
        rejection = qv.get("reject_reason")
        contract_failures = qv.get("contract_failures") or []
        if rejection == "contract" and contract_failures:
            rejection = "contract: " + "; ".join(str(value) for value in contract_failures)
        return {
            "factor_id": genome.fingerprint(),
            "family": template.get("hypothesis", "ga-search")[:60] if template else "ga-search",
            "edit_type": self._derive_edit_type(genome, parent_id),
            "parent_id": parent_id,
            "hypothesis": (template or {}).get("hypothesis", "GA 无模板搜索"),
            "round_no": round_no,
            "mechanism_slot": (template or {}).get("mechanism_slot"),
            "research_track": (template or {}).get("research_track", "ga-only"),
            "proposal_type": (template or {}).get("proposal_type", "ga-only"),
            "parent_factor_ids": parent_ids,
            "ex_ante_sign": (template or {}).get("ex_ante_sign", "+"),
            "sign_observed": "+" if (
                neutral_ic if isinstance(neutral_ic, (int, float))
                else detail.get("rank_ic", 0)
            ) >= 0 else "-",
            "split": "train",
            "window": f"{self.config['panel']['start']}..{self.config['panel']['end']}",
            "window_start": self.config["panel"]["start"],
            "window_end": self.config["panel"]["end"],
            "verdict": verdict,
            "kill_reason": None if verdict == "keep" else (
                rejection
                or ("fitness<=0 in local quick screen" if not quick_ok else
                    "score_factor 三级联未通过")
            ),
            "attribution": (
                f"{(template or {}).get('research_track', 'ga-only')} mechanism + "
                "adaptive GA + quick_fitness 粗筛 + score_factor 完整三级联"
            ),
            "script": "automation/loop/run_round.py",
            "metrics": metrics,
            "stage_reached": qv.get("stage_reached"),
            "preprocessing": qv.get("preprocessing", {}),
            "cost": {"wall_seconds": None, "platform": None},
            # 保存完整 genome 结构，支撑后续 notebook 生成和策略审计
            "genome": genome.to_dict(),
            "genome_expression": genome.to_expression(),
        }

    def _derive_edit_type(self, genome: Genome, parent_id: str | None) -> str:
        if parent_id is None:
            return "new-family"
        parent = self._genomes.get(parent_id)
        if parent is None:
            raise RuntimeError(f"ledger 派生关系缺少父 genome: {parent_id}")
        if len(genome.blocks) != len(parent.blocks):
            return "add-interaction" if len(genome.blocks) > len(parent.blocks) else "operator-swap"
        if genome.combine != parent.combine:
            return "rank-switch"
        if [block.op for block in genome.blocks] != [block.op for block in parent.blocks]:
            return "operator-swap"
        if [block.inputs for block in genome.blocks] != [block.inputs for block in parent.blocks]:
            return "feature-swap"
        if [block.params for block in genome.blocks] != [block.params for block in parent.blocks]:
            return "window-rescale"
        return "normalization-change"

    def _append_ledger(self, record: dict) -> None:
        """Write through the validated append-only ledger; invalid records are fatal."""
        ledger_append(self.run_dir, record)
        self._recorded_ids.add(str(record["factor_id"]))
        self._records_by_id[str(record["factor_id"])] = record

    def _append_platform_to_ledger(self, factor_id: str, presult: dict) -> None:
        """将平台评估结果作为独立记录追加到 ledger。"""
        metrics = presult.get("metrics", {})
        record = {
            "factor_id": f"{factor_id}__platform",
            "family": "platform-eval",
            "edit_type": "platform-eval",
            "parent_id": factor_id,
            "hypothesis": f"AIStudio 平台评估回写 (原始因子: {factor_id})",
            "ex_ante_sign": "+",
            "sign_observed": "+" if metrics.get("rank_ic", 0) >= 0 else "-",
            "split": "platform",
            "window": f"{self.config['panel']['start']}..{self.config['panel']['end']}",
            "window_start": self.config["panel"]["start"],
            "window_end": self.config["panel"]["end"],
            "verdict": "platform",
            "kill_reason": None,
            "attribution": "CDP → AIStudio terminal → parse",
            "script": "automation/loop/platform_eval.py",
            "metrics": {k: round(v, 4) if isinstance(v, float) else v
                       for k, v in metrics.items()},
            "stage_reached": "platform",
            "cost": {"wall_seconds": None, "platform": "AIStudio CDP"},
        }
        self._append_ledger(record)
