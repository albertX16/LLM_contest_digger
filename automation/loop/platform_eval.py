"""Strict, optional AIStudio artifact uploader.

Local research and BARRA-neutralized backtests do not depend on this module.
When upload is explicitly enabled, any upload problem raises and stops the run.
This module never evaluates a fake SQL payload and never clicks final submit.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


NODE = (
    "/Users/azul1024/.cache/codex-runtimes/codex-primary-runtime/"
    "dependencies/node/bin/node"
)
UPLOAD_SCRIPT = str(Path(__file__).with_name("edge_aistudio_upload_verified.mjs"))
REMOTE_DIR = "/home/aiuser/work/automation_submissions"


class PlatformEvaluator:
    def __init__(self) -> None:
        self.submitted: list[dict[str, Any]] = []

    def upload_artifact(self, local_path: str | Path,
                        remote_name: str | None = None) -> dict[str, Any]:
        """Upload a validated notebook; raise on every failure."""
        local = Path(local_path)
        if not local.is_file():
            raise FileNotFoundError(f"待上传 artifact 不存在: {local}")
        if local.suffix not in {".ipynb", ".py"}:
            raise ValueError(f"不支持的 artifact 类型: {local.suffix}")
        script = Path(UPLOAD_SCRIPT)
        if not script.is_file():
            raise FileNotFoundError(f"AIStudio 上传脚本不存在: {script}")
        remote_path = f"{REMOTE_DIR}/{remote_name or local.name}"
        completed = subprocess.run(
            [NODE, str(script), str(local), remote_path],
            capture_output=True, text=True, timeout=60,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"AIStudio 上传失败 rc={completed.returncode}: "
                f"{completed.stderr[:500]}"
            )
        result = {
            "ok": True,
            "local_path": str(local),
            "remote_path": remote_path,
            "factor_id": local.stem,
            "official_evaluation_status": "not_run",
        }
        self.submitted.append(result)
        return result
