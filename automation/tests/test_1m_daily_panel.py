"""2024 1m -> 日频特征面板：存储降型、季度缓存校验、特征构建、主流程接入。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from automation.panel.daily_features import (
    DAILY_FIELDS,
    build_daily_features,
    build_quarter_features,
)
from automation.panel.fetch_1m import (
    downcast_1m,
    ensure_1m_cache,
    iter_1m_chunks,
    list_1m_quarters,
)


def make_synthetic_1m(days: int = 3, instruments: int = 20,
                      bars_per_day: int = 240) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    times = pd.date_range("2024-01-02 09:31:00", periods=240, freq="1min")
    rows = []
    for day_index in range(days):
        day = pd.Timestamp("2024-01-02") + pd.Timedelta(days=day_index)
        for ts0 in times:
            ts = pd.Timestamp(f"{day.date()} {ts0.strftime('%H:%M:%S')}")
            for instrument in range(1, instruments + 1):
                rows.append((ts, instrument))
    frame = pd.DataFrame(rows, columns=["date", "instrument"])
    frame["open"] = 10 + rng.standard_normal(len(frame)).cumsum() % 20
    frame["high"] = frame["open"] * 1.002
    frame["low"] = frame["open"] * 0.998
    frame["close"] = frame["open"] * (1 + rng.standard_normal(len(frame)) * 0.001)
    frame["volume"] = rng.integers(1000, 50000, len(frame)).astype("float32")
    frame["amount"] = frame["close"] * frame["volume"]
    frame["deal_number"] = rng.integers(1, 50, len(frame)).astype("int32")
    frame["adjust_factor"] = 1.0
    for level in (1, 2, 3):
        frame[f"bid_price{level}"] = frame["close"] * (1 - 0.001 * level)
        frame[f"ask_price{level}"] = frame["close"] * (1 + 0.001 * level)
        frame[f"bid_volume{level}"] = (frame["volume"] / level).astype("float32")
        frame[f"ask_volume{level}"] = (frame["volume"] / (level + 1)).astype("float32")
        frame[f"bid_num_orders{level}"] = rng.integers(1, 30, len(frame)).astype("int32")
        frame[f"ask_num_orders{level}"] = rng.integers(1, 30, len(frame)).astype("int32")
    frame["date"] = pd.to_datetime(frame["date"])
    return frame


def test_downcast_reduces_memory() -> None:
    frame = make_synthetic_1m(days=1, instruments=5)
    out = downcast_1m(frame.rename(columns={"instrument": "instrument_id"}))
    assert out["instrument_id"].dtype == np.int16
    assert out["close"].dtype == np.float32
    assert out["amount"].dtype == np.float64
    assert out["deal_number"].dtype == np.int32


def test_build_quarter_features_shape_and_contract() -> None:
    frame = make_synthetic_1m(days=2, instruments=15)
    daily = build_quarter_features(frame)
    assert len(daily) == 2 * 15
    assert set(DAILY_FIELDS).issubset(daily.columns)
    nums = daily.select_dtypes("number")
    assert int((nums.abs() == float("inf")).sum().sum()) == 0
    assert "date" in daily.columns and "instrument" in daily.columns


def test_quarter_cache_and_build_end_to_end(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    frame = make_synthetic_1m(days=3, instruments=20)
    quarter = cache_dir / "raw_1m_2024-01-02_2024-01-04.parquet"
    downcast_1m(frame).to_parquet(quarter, index=False)
    chunks = list(iter_1m_chunks("2024-01-02", "2024-01-04", cache_dir))
    assert len(chunks) == 1
    assert len(chunks[0]) == 3 * 20 * 240

    out_path = tmp_path / "panel.parquet"
    panel = build_daily_features(
        "2024-01-02", "2024-01-04", cache_dir, out_path)
    assert len(panel) == 3 * 20
    assert set(DAILY_FIELDS).issubset(panel.columns)
    assert len(list_1m_quarters(cache_dir)) == 1


def test_bad_quarter_cache_is_rejected(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    # 只有 1 天、且时间戳被压成纯日期的坏缓存必须被拒绝。
    bad = pd.DataFrame({
        "date": ["2024-01-02"] * 10,
        "instrument": [1] * 10,
        "close": [1.0] * 10,
    })
    bad.to_parquet(
        cache_dir / "raw_1m_2024-01-02_2024-01-04.parquet", index=False)
    with pytest.raises(ValueError):
        list(iter_1m_chunks("2024-01-02", "2024-01-04", cache_dir))


def test_ensure_cache_requires_quarterly_files(tmp_path: Path, monkeypatch) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    frame = make_synthetic_1m(days=1, instruments=4)
    monkeypatch.setattr(
        "automation.panel.fetch_1m.query_bar",
        lambda *args, **kwargs: frame.rename(columns={"instrument": "instrument_id"}),
    )
    paths = ensure_1m_cache("2024-01-02", "2024-01-04", cache_dir)
    assert len(paths) == 1
    assert paths[0].exists()


def test_holiday_week_empty_is_valid_cache(tmp_path: Path, monkeypatch) -> None:
    """2024 春节休市周（2/12-2/18）返回空是合法缓存，不当作下载失败。"""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    def empty_query(*args, **kwargs):
        return pd.DataFrame()

    monkeypatch.setattr("automation.panel.fetch_1m.query_bar", empty_query)
    paths = ensure_1m_cache("2024-02-12", "2024-02-18", cache_dir)
    assert len(paths) == 1
    marker = pd.read_parquet(paths[0])
    assert marker.empty
    chunks = list(iter_1m_chunks("2024-02-12", "2024-02-18", cache_dir))
    assert chunks[0].empty
