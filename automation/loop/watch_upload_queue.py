"""Upload completed-round notebooks in verified, per-round AIStudio batches."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
NODE = (
    "/Users/azul1024/.cache/codex-runtimes/codex-primary-runtime/"
    "dependencies/node/bin/node"
)
UPLOADER = Path(__file__).with_name("edge_aistudio_upload_verified.mjs")
REMOTE_ROOT = "/home/aiuser/work/automation_submissions"

log = logging.getLogger("upload_queue")


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_state(path: Path) -> dict:
    if not path.exists():
        return {
            "schema_version": 1,
            "remote_root": REMOTE_ROOT,
            "batches": {},
        }
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1 or not isinstance(raw.get("batches"), dict):
        raise ValueError("upload_queue_state schema 非法")
    return raw


def save_state(path: Path, state: dict) -> None:
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def round_files(run_dir: Path, summary: dict) -> list[tuple[Path, str]] | None:
    round_no = int(summary["round_no"])
    if round_no == 3:
        probe_manifest = run_dir / "round_3_platform_probes" / "manifest.json"
        if not probe_manifest.exists():
            return None
        raw = json.loads(probe_manifest.read_text(encoding="utf-8"))
        files = [
            (Path(item["notebook"]), Path(item["notebook"]).name)
            for item in raw.get("factors", [])
        ]
        if not files:
            raise RuntimeError("Round 3 probe manifest 没有候选 notebook")
        return files

    ledger = {
        str(record.get("factor_id")): record
        for record in read_jsonl(run_dir / "ledger.jsonl")
    }
    files = []
    for item in summary.get("prepared_artifacts", []):
        local = Path(item["local_path"])
        factor_id = str(item["factor_id"])
        record = ledger.get(factor_id, {})
        slot = int(record.get("mechanism_slot", 0) or 0)
        remote_name = f"r{round_no:03d}_m{slot:02d}_{factor_id}.ipynb"
        files.append((local, remote_name))
    return files


def upload(local: Path, remote: str) -> dict:
    if not local.is_file():
        raise FileNotFoundError(f"待上传文件不存在: {local}")
    completed = subprocess.run(
        [NODE, str(UPLOADER), str(local), remote],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"AIStudio 验证上传失败 rc={completed.returncode}: "
            f"{completed.stderr[-1000:]}"
        )
    result = json.loads(completed.stdout)
    expected = sha256(local)
    if not result.get("ok") or result.get("remoteSha") != expected:
        raise RuntimeError(f"远端哈希未验证: {result}")
    return result


def ensure_batch(state: dict, round_no: int) -> dict:
    key = str(round_no)
    if key in state["batches"]:
        return state["batches"][key]
    used = [int(item["batch_number"]) for item in state["batches"].values()]
    number = max(used, default=0) + 1
    batch = {
        "batch_number": number,
        "round_no": round_no,
        "remote_folder": f"{REMOTE_ROOT}/batch_{number:03d}_round_{round_no:03d}",
        "status": "waiting",
        "files": {},
        "created_at": now(),
    }
    state["batches"][key] = batch
    return batch


def process_once(run_dir: Path, state_path: Path, start_round: int) -> bool:
    state = load_state(state_path)
    summaries = sorted(
        (item for item in read_jsonl(run_dir / "round_summary.jsonl")
         if int(item.get("round_no", 0)) >= start_round),
        key=lambda item: int(item["round_no"]),
    )
    changed = False
    for summary in summaries:
        round_no = int(summary["round_no"])
        files = round_files(run_dir, summary)
        if files is None:
            continue
        batch = ensure_batch(state, round_no)
        if batch.get("status") == "verified_complete":
            continue
        batch["status"] = "uploading"
        save_state(state_path, state)
        for local, remote_name in files:
            local = local if local.is_absolute() else ROOT / local
            remote = f"{batch['remote_folder']}/{remote_name}"
            expected = sha256(local)
            previous = batch["files"].get(str(local), {})
            if (previous.get("status") == "verified"
                    and previous.get("sha256") == expected):
                continue
            result = upload(local, remote)
            batch["files"][str(local)] = {
                "status": "verified",
                "remote_path": remote,
                "sha256": result["remoteSha"],
                "bytes": result["bytes"],
                "uploaded_at": now(),
            }
            save_state(state_path, state)

        manifest_dir = run_dir / "upload_manifests"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / (
            f"batch_{batch['batch_number']:03d}_round_{round_no:03d}.json")
        remote_manifest = f"{batch['remote_folder']}/manifest.json"
        batch["status"] = "verified_complete"
        batch["completed_at"] = now()
        manifest_path.write_text(json.dumps({
            "batch_number": batch["batch_number"],
            "round_no": round_no,
            "remote_folder": batch["remote_folder"],
            "upload_status": "verified_complete",
            "official_evaluation_status": "not_run",
            "final_submission_status": "not_submitted",
            "files": list(batch["files"].values()),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        upload(manifest_path, remote_manifest)
        batch["manifest_remote_path"] = remote_manifest
        save_state(state_path, state)
        log.info("Round %d uploaded and hash-verified at %s",
                 round_no, batch["remote_folder"])
        changed = True
    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--start-round", type=int, default=3)
    parser.add_argument("--poll-seconds", type=int, default=30)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    run_dir = Path(args.run_dir)
    state_path = run_dir / "upload_queue_state.json"
    while True:
        try:
            process_once(run_dir, state_path, args.start_round)
        except Exception as exc:
            log.warning("upload queue waiting/retrying: %s", exc)
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
