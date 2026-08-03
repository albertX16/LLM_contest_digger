"""基于运行产物的研究进程监督（不依赖 ps，沙箱内可直接运行）。

用法：
    .venv/bin/python scripts/supervise_research.py \
        --run-dir automation/runs/run_2024_1m_v1 [--watch]

输出：
- 当前完整轮次、各轮候选/保留数；
- search_state.json 最后保存时间（last_completed_round / saved_at）；
- 最近 3 条 round_summary 的摘要；
- 若产物超过 threshold 秒未更新，提示"进程可能已停止"。
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _load_summaries(run_dir: Path) -> list[dict]:
    path = run_dir / "round_summary.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def report(run_dir: Path, stall_seconds: int = 600) -> str:
    run_dir = Path(run_dir)
    lines: list[str] = []
    lines.append(f"== 监督报告 {_now()} | run_dir={run_dir}")
    summaries = _load_summaries(run_dir)
    if summaries:
        lines.append(f"完整轮次: {len(summaries)}")
        for item in summaries[-3:]:
            lines.append(
                f"  round {item['round_no']}: wall={item['wall_seconds']}s "
                f"cand={item['n_candidates']} kept={item['n_kept']} "
                f"prepared={item['n_prepared']} ts={item['ts']}"
            )
    else:
        lines.append("尚无完整轮次（正在第一轮 GA / Planner 阶段）")

    state_path = run_dir / "search_state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        saved_at = state.get("saved_at", "?")
        last_round = state.get("last_completed_round")
        lines.append(f"持久化状态: last_completed_round={last_round} saved_at={saved_at}")
        age = time.time() - state_path.stat().st_mtime
        if age > stall_seconds:
            lines.append(
                f"⚠ search_state 已 {age/60:.0f} 分钟未更新——进程可能已停止"
                "（也可能正处于耗时极长的完整评分阶段，请对照外部 Terminal 日志）")
    ledger = run_dir / "ledger.jsonl"
    if ledger.exists():
        n = sum(1 for _ in ledger.open())
        lines.append(f"ledger 记录: {n}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="研究进程监督（产物驱动）")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--watch", action="store_true",
                        help="每 60 秒刷新一次")
    args = parser.parse_args()
    if args.watch:
        while True:
            print(report(args.run_dir))
            print("-" * 60, flush=True)
            time.sleep(60)
    print(report(args.run_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
