"""2024 1 分钟 bar 的本地缓存层（内存安全设计）。

设计目标：
1. 全年 1 分钟数据约 5800 万行，不能一次性读进内存（约 8GB）。
2. 服务端单次读取上限 200MB：1m 数据一个季度约 1.6GB，必须用周块下载
   （一周约 130MB），每块独立缓存 raw_1m_<起>_<止>.parquet，
   失败重跑自动跳过已完成块；
3. 存储层做 float32/int32 降型，压缩体积并降低读取内存；
4. 提供 iter_1m_chunks() 逐块流式读取，调用方处理完一块即释放，
   峰值内存只等于一个周块（约 200MB），而不是全年。

缓存校验沿用 fetch.py 的硬规则：真实日内时刻、请求区间端点、逐月连续性，
任何覆盖不完整的缓存都拒绝命中。
"""

from __future__ import annotations

import glob
from pathlib import Path

import pandas as pd

from automation.panel.fetch import (
    _covers_requested_range,
    _has_monthly_continuity,
    _is_intraday_frame,
    query_bar,
)


TABLE_1M = "bigalpha_2026_e2e_bar1m"

# A 股全年休市周（固定 7 天滑动窗口恰好完全落在假期内）。
# 2024：春节 2/9-2/17 休市，2/12-2/18 窗口无任何交易日。
HOLIDAY_WEEKS_2024 = {("2024-02-12", "2024-02-18")}

_EMPTY_SCHEMA_COLS = [
    "date", "instrument", "adjust_factor", "high", "open", "low", "close",
    "deal_number", "volume", "amount",
    "ask_price1", "ask_price2", "ask_price3",
    "bid_price1", "bid_price2", "bid_price3",
    "ask_volume1", "ask_volume2", "ask_volume3",
    "bid_volume1", "bid_volume2", "bid_volume3",
    "ask_num_orders1", "ask_num_orders2", "ask_num_orders3",
    "bid_num_orders1", "bid_num_orders2", "bid_num_orders3",
]


def _is_all_holiday(chunk_start: str, chunk_end: str) -> bool:
    return (chunk_start, chunk_end) in HOLIDAY_WEEKS_2024

# 存储降型规则：价格/挂单量/笔数用 float32（数值 < 2^24 可精确表示），
# 成交额可能到 10^10 保留 float64，成交笔数用 int32。
FLOAT32_COLS = {
    "adjust_factor", "high", "open", "low", "close",
    "ask_price1", "ask_price2", "ask_price3",
    "bid_price1", "bid_price2", "bid_price3",
    "ask_volume1", "ask_volume2", "ask_volume3",
    "bid_volume1", "bid_volume2", "bid_volume3",
    "ask_num_orders1", "ask_num_orders2", "ask_num_orders3",
    "bid_num_orders1", "bid_num_orders2", "bid_num_orders3",
    "volume",
}
INT32_COLS = {"deal_number"}
FLOAT64_COLS = {"amount"}


def downcast_1m(frame: pd.DataFrame) -> pd.DataFrame:
    """把 1m 缓存降型，减少约一半内存与磁盘。"""
    out = frame.copy()
    for col in FLOAT32_COLS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").astype("float32")
    for col in INT32_COLS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").astype("int32")
    for col in FLOAT64_COLS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").astype("float64")
    if "instrument_id" in out.columns:
        out["instrument_id"] = out["instrument_id"].astype("int16")
    if "instrument" in out.columns:
        out["instrument"] = pd.to_numeric(out["instrument"], errors="coerce").astype(
            "int16")
    return out


def _validate_chunk(frame: pd.DataFrame, chunk_start: str, chunk_end: str,
                    path: Path) -> None:
    if frame.empty and _is_all_holiday(chunk_start, chunk_end):
        return  # 全年休市周（如春节）合法空缓存
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    span_days = int((pd.Timestamp(chunk_end) - pd.Timestamp(chunk_start)).days)
    # 周块粒度下不做块级逐月连续性（跨月周块的下月可能只有周末）；
    # 逐月连续性改在全年合并结果上校验。
    monthly_ok = (span_days <= 10
                  or _has_monthly_continuity(frame, chunk_start, chunk_end))
    if (not _covers_requested_range(frame, chunk_start, chunk_end)
            or not _is_intraday_frame(frame)
            or not monthly_ok):
        raise ValueError(
            f"1m 季度缓存覆盖不完整 {chunk_start}..{chunk_end}: "
            f"{frame['date'].min()}..{frame['date'].max()} ({path})"
        )


def _chunk_ranges(start: str, end: str, days: int = 7) -> list[tuple[str, str]]:
    """按周（默认 7 个自然日）切分请求区间。

    服务端单次读取上限 200MB；1m 数据一周约 1.2M 行 / 130MB，
    是唯一既能完整返回又不超限的粒度。
    """
    first = pd.Timestamp(start).normalize()
    last = pd.Timestamp(end).normalize()
    if first > last:
        raise ValueError(f"start 晚于 end: {start} > {end}")
    ranges: list[tuple[str, str]] = []
    cursor = first
    while cursor <= last:
        chunk_end = min(cursor + pd.Timedelta(days=days - 1), last)
        ranges.append((cursor.strftime("%Y-%m-%d"),
                       chunk_end.strftime("%Y-%m-%d")))
        cursor = chunk_end + pd.Timedelta(days=1)
    return ranges


def fetch_raw_1m(
    start: str,
    end: str,
    cache_dir: str | Path = "data_cache/dai_download",
    table: str = TABLE_1M,
) -> pd.DataFrame:
    """确保 [start, end] 的 1m 数据按季度落盘，返回按请求区间拼接的 DataFrame。

    返回全年会占用较大内存；调用方应优先使用 iter_1m_chunks() 逐块处理。
    此函数主要用于核对完整性或小范围使用。
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    parts: list[pd.DataFrame] = []
    for chunk_start, chunk_end in _chunk_ranges(start, end):
        name = f"raw_1m_{chunk_start}_{chunk_end}.parquet"
        path = cache_dir / name
        if path.exists():
            frame = pd.read_parquet(path)
            _validate_chunk(frame, chunk_start, chunk_end, path)
        else:
            try:
                frame = query_bar(table, chunk_start, chunk_end,
                                  columns=None, limit=None)
            except Exception as exc:
                raise RuntimeError(
                    f"1m 季度下载失败 {chunk_start}..{chunk_end}: {exc}"
                ) from exc
            if frame.empty and not _is_all_holiday(chunk_start, chunk_end):
                raise RuntimeError(
                    f"1m 季度查询 {table} [{chunk_start}, {chunk_end}] 返回空")
            if frame.empty:
                pd.DataFrame(columns=_EMPTY_SCHEMA_COLS).to_parquet(
                    path, index=False)
                print(f"[fetch_1m] 全假期周空缓存 -> {path.name}")
                continue
            frame = downcast_1m(frame)
            _validate_chunk(frame, chunk_start, chunk_end, path)
            frame.to_parquet(path, index=False)
            print(f"[fetch_1m] 季度缓存 {len(frame)} 行 -> {path.name}")
        parts.append(frame)
    combined = pd.concat(parts, ignore_index=True)
    combined = combined.drop_duplicates(["date", "instrument"], keep="last")
    combined = combined.sort_values(["date", "instrument"]).reset_index(drop=True)
    if not _covers_requested_range(combined, start, end):
        raise ValueError(f"1m 季度合并后仍未覆盖 {start}..{end}")
    span_days = int((pd.Timestamp(end) - pd.Timestamp(start)).days)
    if span_days > 10 and not _has_monthly_continuity(combined, start, end):
        raise ValueError(f"1m 全年合并后逐月不连续 {start}..{end}")
    return combined


def iter_1m_chunks(
    start: str,
    end: str,
    cache_dir: str | Path = "data_cache/dai_download",
    columns: list[str] | None = None,
    table: str = TABLE_1M,
):
    """逐季度产出 1m 数据块（yield 后由调用方释放），峰值内存只占一个季度。

    缺失的季度会当场下载并缓存；已缓存的季度只读需要的列。
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    for chunk_start, chunk_end in _chunk_ranges(start, end):
        name = f"raw_1m_{chunk_start}_{chunk_end}.parquet"
        path = cache_dir / name
        if not path.exists():
            try:
                frame = query_bar(table, chunk_start, chunk_end,
                                  columns=None, limit=None)
            except Exception as exc:
                raise RuntimeError(
                    f"1m 季度下载失败 {chunk_start}..{chunk_end}: {exc}"
                ) from exc
            if frame.empty and not _is_all_holiday(chunk_start, chunk_end):
                raise RuntimeError(
                    f"1m 季度查询 {table} [{chunk_start}, {chunk_end}] 返回空")
            if frame.empty:
                pd.DataFrame(columns=_EMPTY_SCHEMA_COLS).to_parquet(
                    path, index=False)
                print(f"[fetch_1m] 全假期周空缓存 -> {path.name}")
                continue
            frame = downcast_1m(frame)
            _validate_chunk(frame, chunk_start, chunk_end, path)
            frame.to_parquet(path, index=False)
            print(f"[fetch_1m] 季度缓存 {len(frame)} 行 -> {path.name}")
        else:
            frame = pd.read_parquet(path, columns=columns)
            _validate_chunk(frame, chunk_start, chunk_end, path)
        yield frame
        del frame


def ensure_1m_cache(
    start: str,
    end: str,
    cache_dir: str | Path = "data_cache/dai_download",
    table: str = TABLE_1M,
) -> list[Path]:
    """只确保季度缓存齐全（不拼接全年），返回已落盘的季度文件列表。"""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for chunk_start, chunk_end in _chunk_ranges(start, end):
        name = f"raw_1m_{chunk_start}_{chunk_end}.parquet"
        path = cache_dir / name
        if not path.exists():
            frame = query_bar(table, chunk_start, chunk_end, columns=None, limit=None)
            if frame.empty and not _is_all_holiday(chunk_start, chunk_end):
                raise RuntimeError(
                    f"1m 季度查询 {table} [{chunk_start}, {chunk_end}] 返回空")
            if frame.empty:
                pd.DataFrame(columns=_EMPTY_SCHEMA_COLS).to_parquet(
                    path, index=False)
                print(f"[fetch_1m] 全假期周空缓存 -> {path.name}")
                paths.append(path)
                continue
            frame = downcast_1m(frame)
            _validate_chunk(frame, chunk_start, chunk_end, path)
            frame.to_parquet(path, index=False)
            print(f"[fetch_1m] 季度缓存 {len(frame)} 行 -> {path.name}")
        paths.append(path)
    return paths


def list_1m_chunks(cache_dir: str | Path = "data_cache/dai_download") -> list[Path]:
    return sorted(glob.glob(str(Path(cache_dir) / "raw_1m_*.parquet")))


list_1m_quarters = list_1m_chunks  # 兼容旧名
