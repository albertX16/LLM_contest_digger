"""Build per-mechanism platform probes after a completed research round.

This is deliberately outside the scoring loop: a platform probe may be the
best member of a mechanism even when the local cascade retired it.  The
manifest preserves that verdict instead of relabelling the probe as a keep.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.evaluate.expr import eval_genome
from automation.loop.rewrite_queue import write_spec
from automation.panel.fetch import fetch_raw_30m, to_daily_factor
from automation.search.genome import Genome


def learning_score(record: dict) -> float:
    metrics = record.get("metrics", {})
    keep_bonus = 1000.0 if record.get("verdict") == "keep" else 0.0
    return (
        keep_bonus
        + float(metrics.get("fitness", 0.0) or 0.0)
        + float(metrics.get("neutralized_rank_ic_tstat", 0.0) or 0.0)
        - float(metrics.get("max_corr_refset", 1.0) or 0.0)
    )


def mean_cross_sectional_corr(left: pd.DataFrame, right: pd.DataFrame) -> float:
    dates = left.index.intersection(right.index)
    names = left.columns.intersection(right.columns)
    if dates.empty or names.empty:
        raise ValueError("候选之间没有共同日期/标的，无法验证正交性")
    daily = left.loc[dates, names].corrwith(
        right.loc[dates, names], axis=1, method="spearman").dropna()
    if daily.empty:
        raise ValueError("候选之间的逐日截面相关全部为空")
    return float(daily.abs().mean())


def update_leader_sequence(config: dict, round_no: int,
                           selected: list[dict]) -> None:
    """Persist exactly one local leader per mechanism for future planners."""
    sequence_file = config.get("search", {}).get("leader_sequence_file")
    if not sequence_file:
        raise ValueError("search.leader_sequence_file 未配置")
    path = Path(sequence_file)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1 or not isinstance(raw.get("leaders"), list):
        raise ValueError("leader_factor_sequence schema 非法")

    feedback_file = config.get("search", {}).get("platform_feedback_file")
    if feedback_file:
        feedback = json.loads(Path(feedback_file).read_text(encoding="utf-8"))
        feedback_by_id = {
            str(item["factor_id"]): item for item in feedback.get("factors", [])
        }
        for leader in raw["leaders"]:
            item = feedback_by_id.get(str(leader.get("factor_id")))
            if item is None:
                continue
            score = item.get("reported_score")
            leader["reported_score"] = score
            leader["score_precision"] = item.get("precision")
            for key in ("observed_at", "score_scope", "reported_rank_impact"):
                if key in item:
                    leader[key] = item[key]
            if score is not None:
                history = list(leader.get("score_history", []))
                if score not in history:
                    history.append(score)
                leader["score_history"] = history

    existing = {str(item.get("factor_id")) for item in raw["leaders"]}
    primaries = [
        item["record"] for item in selected
        if item["selection_reason"] == "best_within_mechanism"
    ]
    for record in sorted(primaries, key=lambda item: item["mechanism_slot"]):
        factor_id = str(record["factor_id"])
        if factor_id in existing:
            continue
        raw["leaders"].append({
            "factor_id": factor_id,
            "display_name": (
                f"Round {round_no} mechanism {record['mechanism_slot']} local leader"
            ),
            "evidence_scope": "local_unconfirmed",
            "priority": "round_leader",
            "round_no": round_no,
            "mechanism_slot": record["mechanism_slot"],
            "research_track": record.get("research_track"),
            "verdict": record.get("verdict"),
            "metrics": record.get("metrics", {}),
            "mechanism": record.get("hypothesis"),
            "genome_expression": record.get("genome_expression"),
        })
        existing.add(factor_id)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def build_handoff(config: dict, run_dir: Path, round_no: int) -> dict:
    ledger_path = run_dir / "ledger.jsonl"
    records = [
        json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    records = [record for record in records if record.get("round_no") == round_no]
    mechanisms = int(config["search"].get("mechanisms_per_round", 4))
    grouped = {
        slot: [record for record in records if record.get("mechanism_slot") == slot]
        for slot in range(1, mechanisms + 1)
    }
    missing = [slot for slot, values in grouped.items() if not values]
    if missing:
        raise RuntimeError(f"Round {round_no} 缺少机制候选: {missing}")

    panel = config["panel"]
    frame = fetch_raw_30m(
        panel["start"], panel["end"], panel["cache_dir"], panel["source_table"])
    frame["date"] = pd.to_datetime(frame["date"])
    wide: dict[str, pd.DataFrame] = {}
    for record in records:
        genome = Genome.from_dict(record["genome"])
        daily = to_daily_factor(eval_genome(genome, frame), frame)
        wide[record["factor_id"]] = daily.pivot(
            index="date", columns="instrument", values="factor")

    selected: list[dict] = []
    for slot, values in grouped.items():
        ranked = sorted(values, key=learning_score, reverse=True)
        primary = ranked[0]
        selected.append({
            "record": primary,
            "selection_reason": "best_within_mechanism",
            "pair_corr_vs_primary": None,
        })
        primary_fitness = float(primary.get("metrics", {}).get("fitness", 0.0) or 0.0)
        alternatives = []
        for candidate in ranked[1:]:
            if candidate.get("verdict") != "keep":
                continue
            candidate_fitness = float(
                candidate.get("metrics", {}).get("fitness", 0.0) or 0.0)
            if primary_fitness > 0 and candidate_fitness < 0.75 * primary_fitness:
                continue
            corr = mean_cross_sectional_corr(
                wide[primary["factor_id"]], wide[candidate["factor_id"]])
            if abs(corr) <= 0.50:
                alternatives.append((candidate, corr))
        if alternatives:
            candidate, corr = max(alternatives, key=lambda item: learning_score(item[0]))
            selected.append({
                "record": candidate,
                "selection_reason": "second_strong_and_return_orthogonal",
                "pair_corr_vs_primary": corr,
            })

    output_dir = run_dir / "agent_rewrite_queue" / f"round_{round_no:03d}"
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_rows = []
    for item in selected:
        record = item["record"]
        path, _ = write_spec(
            output_dir,
            record,
            round_no,
            selection_reason=item["selection_reason"],
            pair_corr_vs_primary=item["pair_corr_vs_primary"],
        )
        manifest_rows.append({
            "factor_id": record["factor_id"],
            "mechanism_slot": record["mechanism_slot"],
            "research_track": record.get("research_track"),
            "hypothesis": record.get("hypothesis"),
            "local_verdict": record.get("verdict"),
            "local_kill_reason": record.get("kill_reason"),
            "metrics": record.get("metrics", {}),
            "selection_reason": item["selection_reason"],
            "pair_corr_vs_primary": item["pair_corr_vs_primary"],
            "factor_spec": str(path),
            "rewrite_status": "pending_agent_rewrite",
        })

    manifest = {
        "round_no": round_no,
        "selection_policy": {
            "minimum_per_mechanism": 1,
            "optional_second": (
                "local keep; fitness >= 75% of primary; "
                "mean absolute daily cross-sectional Spearman corr <= 0.50"
            ),
            "artifact_mode": "pending_agent_rewrite",
            "automatic_notebook_generation": False,
            "platform_submission_status": "not_uploaded_not_submitted",
        },
        "factors": manifest_rows,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(
        manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    update_leader_sequence(config, round_no, selected)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="automation/configs/default.yaml")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--round", type=int, required=True)
    args = parser.parse_args()
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    manifest = build_handoff(config, Path(args.run_dir), args.round)
    print(json.dumps({
        "round": args.round,
        "n_rewrite_specs": len(manifest["factors"]),
        "mechanisms": sorted({
            item["mechanism_slot"] for item in manifest["factors"]}),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
