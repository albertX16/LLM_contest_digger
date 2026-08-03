"""严格监控：轮询运行状态；异常只暂停，不改变算法或关闭组件。"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)


class Watchdog:
    def __init__(self, run_dir: str | Path, interval_s: int = 60) -> None:
        self.run_dir = Path(run_dir)
        self.interval_s = interval_s
        self.summary_path = self.run_dir / "round_summary.jsonl"
        self.log_path = self.run_dir / "watchdog.log"
        self._seen = 0

    def observe(self, max_stall_rounds: int = 2) -> str:
        """检查一轮后的状态，返回建议动作：'continue' | 'pause'。"""
        summaries = self._read_summaries()
        new = len(summaries) - self._seen
        self._seen = len(summaries)
        if new <= 0:
            self._log("warning", "无新轮次产出")
            return "pause"
        last = summaries[-1]
        if last.get("n_kept", 0) == 0:
            self._log("info", "本轮无保留因子（正常淘汰）")
        return "continue"

    def _read_summaries(self) -> list[dict]:
        if not self.summary_path.exists():
            return []
        return [json.loads(line) for line in
                self.summary_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _log(self, level: str, msg: str) -> None:
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {level}: {msg}\n"
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(line)

    def loop(self, stop_event=None, max_rounds: int | None = None) -> None:
        """阻塞式监控循环（供 CLI 后台任务使用）。"""
        rounds = 0
        while stop_event is None or not stop_event.is_set():
            action = self.observe()
            rounds += 1
            if max_rounds and rounds >= max_rounds:
                self._log("info", "达到最大监控轮数，退出")
                break
            time.sleep(self.interval_s)
