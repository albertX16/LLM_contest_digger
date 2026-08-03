"""下载 2024 全年 1 分钟 bar（按季度缓存）并构建日频特征面板。

用法（需联网/已授权环境）：
    .venv/bin/python scripts/download_1m_2024.py

特性：
- 按周独立缓存 raw_1m_2024-01-01_2024-01-07.parquet 等（服务端单次
  读取上限 200MB，1m 数据周块约 130MB），可断点续传；
- 单季度网络抖动最多重试 5 次，仍失败则明确报错，不静默跳过；
- 全部季度就绪后自动构建 daily_features_2024_1m.parquet（GA 使用的面板）。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from automation.panel.daily_features import build_daily_features  # noqa: E402
from automation.panel.fetch_1m import ensure_1m_cache  # noqa: E402


START = "2024-01-01"
END = "2024-12-31"
CACHE_DIR = "data_cache/dai_download"
FEATURE_PANEL = "data_cache/dai_download/daily_features_2024_1m.parquet"
TABLE = "bigalpha_2026_e2e_bar1m"


def main() -> int:
    cache_dir = Path(CACHE_DIR)
    cache_dir.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            paths = ensure_1m_cache(START, END, cache_dir, TABLE)
            last_error = None
            break
        except Exception as exc:  # 网络抖动重试
            last_error = exc
            print(f"[download_1m_2024] 尝试 {attempt + 1}/5 失败: {exc}")
            time.sleep(15 * (attempt + 1))
    if last_error is not None:
        print(f"[download_1m_2024] 下载失败: {last_error}")
        return 1
    print("[download_1m_2024] 周块缓存齐全:")
    for path in paths:
        print("  ", path, path.stat().st_size / 1e6, "MB")
    panel = build_daily_features(START, END, cache_dir, FEATURE_PANEL, TABLE)
    print(f"[download_1m_2024] 日频特征面板完成: {panel.shape}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
