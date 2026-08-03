"""Write candidate specifications for later Agent-authored platform notebooks."""

from __future__ import annotations

import json
from pathlib import Path

from automation.search.genome import Genome


def factor_spec(record: dict, round_no: int, *, selection_reason: str,
                pair_corr_vs_primary: float | None = None) -> dict:
    genome = Genome.from_dict(record["genome"])
    return {
        "schema_version": 1,
        "artifact_type": "factor_specification",
        "factor_id": record["factor_id"],
        "round_no": round_no,
        "mechanism_slot": record.get("mechanism_slot"),
        "research_track": record.get("research_track"),
        "hypothesis": record.get("hypothesis"),
        "genome": record["genome"],
        "genome_expression": record.get(
            "genome_expression", genome.to_expression()),
        "metrics": record.get("metrics", {}),
        "local_verdict": record.get("verdict"),
        "local_kill_reason": record.get("kill_reason"),
        "selection_reason": selection_reason,
        "pair_corr_vs_primary": pair_corr_vs_primary,
        "rewrite_status": "pending_agent_rewrite",
        "upload_status": "not_uploaded",
        "official_evaluation_status": "not_run",
        "final_submission_status": "not_submitted",
        "rewrite_contract": {
            "author": "interactive_agent_required",
            "platform_examples_required": True,
            "single_main_function_only": True,
            "future_data_prefix_invariance_required": True,
            "automatic_genome_compiler_is_not_submission_authority": True
        }
    }


def write_spec(queue_dir: Path, record: dict, round_no: int, *,
               selection_reason: str,
               pair_corr_vs_primary: float | None = None) -> tuple[Path, dict]:
    queue_dir.mkdir(parents=True, exist_ok=True)
    spec = factor_spec(
        record,
        round_no,
        selection_reason=selection_reason,
        pair_corr_vs_primary=pair_corr_vs_primary,
    )
    slot = int(record.get("mechanism_slot", 0) or 0)
    path = queue_dir / (
        f"r{round_no:03d}_m{slot:02d}_{record['factor_id']}.factor.json")
    path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return path, spec
