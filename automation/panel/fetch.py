"""BigQuant SDK 取数。

复用 scripts/download_bigalpha_e2e_sample.py 的连接方式：进程级代理配置 +
bigquant.init_from_config() + dai.query()。用户指示 e2e 表与 stock_bar1m
"默认相同即可"，因此按同一 schema 处理，不再单独验证。
"""

from __future__ import annotations

import os
import glob
from pathlib import Path
from urllib.request import getproxies

import pandas as pd


def configure_process_proxy() -> str | None:
    """只配置本进程代理；不要改系统网络设置。"""
    proxies = getproxies()
    proxy_url = (
        os.environ.get("BIGQUANT_FLIGHT_PROXY")
        or os.environ.get("grpc_proxy")
        or proxies.get("https")
        or proxies.get("http")
    )
    if proxy_url:
        os.environ["grpc_proxy"] = proxy_url
        os.environ.setdefault("https_proxy", proxy_url)
        os.environ.setdefault("http_proxy", proxy_url)
    return proxy_url


# 必须在按需 import bigquant 之前配置代理。SDK 不能在模块顶层导入，
# 否则合成数据/离线测试也会被一个可选的远端依赖阻断。
ACTIVE_PROXY = configure_process_proxy()


def _sdk():
    try:
        import bigquant
        from bigquant import dai
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "当前 Python 环境未安装 bigquant SDK；真实运行已中止。"
            "请切换到已配置 BigQuant 的环境后重新运行"
        ) from exc
    return bigquant, dai


def init_sdk() -> None:
    """初始化 SDK；认证失败会抛异常。"""
    bigquant, _ = _sdk()
    bigquant.init_from_config()
    if bigquant.get_flight_client() is None:
        raise RuntimeError("Flight client 未初始化（可能需要设置 BIGQUANT_FLIGHT_PROXY）")


def check_quota() -> dict:
    """打印并返回周额度使用情况。"""
    _, dai = _sdk()
    quota = dai.get_data_quota()
    print(f"weekly_quota={quota.get('weekly_quota')} used={quota.get('used_quota')}")
    print(f"authorized: {quota.get('datasources')}")
    return quota


def query_bar(
    table: str,
    start: str,
    end: str,
    columns: list[str] | None = None,
    instruments: list[str] | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    """查询 bar 数据，返回 DataFrame（date, instrument, cols）。"""
    _, dai = _sdk()
    filter_end = end if " " in str(end) else f"{end} 23:59:59"
    cols_clause = ", ".join(columns) if columns else "*"
    sql = f"SELECT {cols_clause} FROM {table}"
    conds = []
    if instruments:
        conds.append(f"instrument_id IN ({', '.join(repr(i) for i in instruments)})")
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY date, instrument_id"
    if limit:
        sql += f" LIMIT {limit}"
    frame = dai.query(
        sql,
        filters={"date": [start, filter_end]},
        compression=True,
        use_studio=False,
    ).df()
    if "instrument_id" in frame.columns:
        frame = frame.rename(columns={"instrument_id": "instrument"})
    # 重复列去重（曾经 SELECT date, instrument_id, * 导致两端都有 date）
    frame = frame.loc[:, ~frame.columns.duplicated()].copy()
    return frame


def fetch_daily_close(
    start: str,
    end: str,
    cache_dir: str | Path = "data_cache/dai_download",
    table: str = "bigalpha_2026_e2e_bar30m",
) -> pd.DataFrame:
    """[DEPRECATED] 按日聚合。请用 fetch_raw_30m() + to_daily_factor()。"""
    return fetch_raw_30m(start, end, cache_dir, table)


def fetch_raw_30m(
    start: str,
    end: str,
    cache_dir: str | Path = "data_cache/dai_download",
    table: str = "bigalpha_2026_e2e_bar30m",
) -> pd.DataFrame:
    """取原始 30m bar 全量列，保留 30m 粒度。支持多文件缓存拼接。

    缓存策略：
    1. 精确缓存文件 raw_30m_{start}_{end}.parquet → 直接命中
    2. 组件缓存文件 raw_30m_*.parquet（按子区间存储）→ 自动拼接并写回合并文件
    3. SDK 网络查询 → 下载并按请求范围写缓存

    列名统一: instrument_id → instrument。
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"raw_30m_{start}_{end}".replace(":", "_")
    cache_path = cache_dir / f"{safe_name}.parquet"
    if cache_path.exists():
        cached = pd.read_parquet(cache_path)
        if (_covers_requested_range(cached, start, end)
                and _is_intraday_frame(cached)
                and _has_monthly_continuity(cached, start, end)):
            print(f"[fetch] 30m 缓存命中: {cache_path}")
            return cached
        print(f"[fetch] 忽略覆盖不完整的缓存: {cache_path}")

    # 2. 尝试从组件缓存拼接
    composed = _compose_from_cache(cache_dir, start, end)
    if composed is not None:
        composed.to_parquet(cache_path, index=False)
        print(f"[fetch] 组件缓存拼接 {len(composed)} 行 -> {cache_path}")
        return composed

    # 3. SDK 网络查询。服务端单次读取上限 200MB，因此固定按季度下载；
    # 每块先独立校验并缓存，失败后重跑会从已完成季度继续。
    raw = _download_quarterly(table, start, end, cache_dir)
    raw["date"] = pd.to_datetime(raw["date"])
    raw.to_parquet(cache_path, index=False)
    print(f"[fetch] 已缓存 {len(raw)} 行 30m -> {cache_path}")
    return raw


def _quarter_ranges(start: str, end: str) -> list[tuple[str, str]]:
    first = pd.Timestamp(start).normalize()
    last = pd.Timestamp(end).normalize()
    if first > last:
        raise ValueError(f"start 晚于 end: {start} > {end}")
    ranges: list[tuple[str, str]] = []
    cursor = first
    while cursor <= last:
        quarter_end = cursor + pd.offsets.QuarterEnd(startingMonth=12)
        chunk_end = min(pd.Timestamp(quarter_end).normalize(), last)
        ranges.append((cursor.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")))
        cursor = chunk_end + pd.Timedelta(days=1)
    return ranges


def _download_quarterly(
    table: str,
    start: str,
    end: str,
    cache_dir: Path,
) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for chunk_start, chunk_end in _quarter_ranges(start, end):
        name = f"raw_30m_{chunk_start}_{chunk_end}.parquet"
        path = cache_dir / name
        if path.exists():
            frame = pd.read_parquet(path)
            if (not _covers_requested_range(frame, chunk_start, chunk_end)
                    or not _is_intraday_frame(frame)
                    or not _has_monthly_continuity(frame, chunk_start, chunk_end)):
                raise ValueError(f"季度缓存覆盖不完整: {path}")
        else:
            try:
                frame = query_bar(table, chunk_start, chunk_end,
                                  columns=None, limit=None)
            except Exception as exc:
                raise RuntimeError(
                    f"季度下载失败 {chunk_start}..{chunk_end}: {exc}"
                ) from exc
            if frame.empty:
                raise RuntimeError(
                    f"季度查询 {table} [{chunk_start}, {chunk_end}] 返回空")
            frame["date"] = pd.to_datetime(frame["date"], errors="raise")
            if (not _covers_requested_range(frame, chunk_start, chunk_end)
                    or not _is_intraday_frame(frame)
                    or not _has_monthly_continuity(frame, chunk_start, chunk_end)):
                raise ValueError(
                    f"季度下载日期覆盖不足 {chunk_start}..{chunk_end}: "
                    f"{frame['date'].min()}..{frame['date'].max()}"
                )
            frame.to_parquet(path, index=False)
            print(f"[fetch] 季度缓存 {len(frame)} 行 -> {path}")
        parts.append(frame)
    combined = pd.concat(parts, ignore_index=True)
    combined = combined.drop_duplicates(["date", "instrument"], keep="last")
    combined = combined.sort_values(["date", "instrument"]).reset_index(drop=True)
    if not _covers_requested_range(combined, start, end):
        raise ValueError(f"季度合并后仍未覆盖 {start}..{end}")
    return combined


def fetch_exposure_panel(
    start: str,
    end: str,
    cache_path: str | Path,
    table: str = "bigalpha_2026_exposure",
) -> pd.DataFrame:
    """Fetch the official BARRA style/industry panel into a local strict cache."""
    path = Path(cache_path)
    if path.exists():
        cached = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
        if _covers_requested_range(cached, start, end):
            return cached
        raise ValueError(f"BARRA exposure 缓存日期覆盖不完整: {path}")
    _, dai = _sdk()
    filter_end = end if " " in str(end) else f"{end} 23:59:59"
    frame = dai.query(
        f"SELECT * FROM {table} ORDER BY date, instrument",
        filters={"date": [start, filter_end]},
        compression=True,
        use_studio=False,
    ).df()
    if frame.empty:
        raise RuntimeError(f"查询 {table} [{start}, {end}] 返回空")
    if "instrument_id" in frame.columns and "instrument" not in frame.columns:
        frame = frame.rename(columns={"instrument_id": "instrument"})
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    if not _covers_requested_range(frame, start, end):
        raise ValueError(f"下载的 BARRA exposure 未覆盖请求区间 {start}..{end}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".parquet":
        frame.to_parquet(path, index=False)
    elif path.suffix == ".csv":
        frame.to_csv(path, index=False)
    else:
        raise ValueError(f"BARRA exposure 缓存仅支持 parquet/csv: {path}")
    return frame


def _compose_from_cache(cache_dir: Path, start: str, end: str) -> pd.DataFrame | None:
    """从目录中多个 raw_30m_*.parquet 文件组装覆盖 [start, end] 的数据。

    返回拼接后的 DataFrame；无匹配时返回 None。
    """
    pattern = str(cache_dir / "raw_30m_*.parquet")
    files = sorted(glob.glob(pattern))
    if not files:
        return None

    # 按文件中的实际日期范围过滤
    parts: list[pd.DataFrame] = []
    for f in files:
        try:
            df = pd.read_parquet(f)
            if "date" not in df.columns or "instrument" not in df.columns:
                raise ValueError("缺少 date/instrument")
            df["date"] = pd.to_datetime(df["date"])
            if not _is_intraday_frame(df):
                print(f"[fetch] 隔离非 30m 时间戳缓存: {f}")
                continue
            start_ts = pd.Timestamp(start)
            end_exclusive = pd.Timestamp(end) + pd.Timedelta(days=1)
            mask = (df["date"] >= start_ts) & (df["date"] < end_exclusive)
            df = df[mask]
            if len(df) > 0:
                parts.append(df)
        except Exception as exc:
            raise RuntimeError(f"读取组件缓存失败，严格模式中止: {f}: {exc}") from exc

    if not parts:
        return None

    composed = pd.concat(parts, ignore_index=True)
    composed = composed.drop_duplicates(subset=["date", "instrument"], keep="last")
    composed = composed.sort_values(["date", "instrument"]).reset_index(drop=True)
    if not _covers_requested_range(composed, start, end):
        return None
    if not _has_monthly_continuity(composed, start, end):
        return None
    print(f"[fetch] 从 {len(parts)}/{len(files)} 个缓存文件拼接 {len(composed)} 行")
    return composed


def _covers_requested_range(frame: pd.DataFrame, start: str, end: str,
                            tolerance_days: int = 10) -> bool:
    """Reject partial caches while allowing exchange holidays (e.g. Golden Week)."""
    if frame.empty or "date" not in frame.columns:
        return False
    dates = pd.to_datetime(frame["date"], errors="coerce").dropna()
    if dates.empty:
        return False
    requested_start = pd.Timestamp(start)
    requested_end = pd.Timestamp(end)
    tolerance = pd.Timedelta(days=tolerance_days)
    return dates.min().normalize() <= requested_start + tolerance and \
        dates.max().normalize() >= requested_end - tolerance


def _is_intraday_frame(frame: pd.DataFrame) -> bool:
    """A 30m cache must retain intraday timestamps, not date-only strings."""
    if frame.empty or "date" not in frame:
        return False
    dates = pd.to_datetime(frame["date"], errors="coerce").dropna()
    if dates.empty:
        return False
    non_midnight = dates.ne(dates.dt.normalize())
    return float(non_midnight.mean()) >= 0.95


def _has_monthly_continuity(frame: pd.DataFrame, start: str, end: str) -> bool:
    """Require every calendar month in the requested interval to be represented."""
    dates = pd.to_datetime(frame["date"], errors="coerce").dropna()
    if dates.empty:
        return False
    expected = set(pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq="M"))
    actual = set(dates.dt.to_period("M"))
    return expected.issubset(actual)


def to_daily_factor(factor_30m: pd.Series, df_30m: pd.DataFrame) -> pd.DataFrame:
    """将 30m 粒度因子聚合成日频 (date, instrument, factor) 长表。

    聚合方法：取每日每只股票最后一根 30m bar 的因子值。
    """
    timestamps = pd.to_datetime(df_30m["date"])
    tmp = pd.DataFrame({
        "timestamp": timestamps.values,
        "date": timestamps.dt.normalize().values,
        "instrument": df_30m["instrument"].values,
        "factor": factor_30m.values.astype(float),
    }, index=factor_30m.index)
    daily = (tmp.sort_values(["instrument", "timestamp"], kind="mergesort")
             .groupby(["date", "instrument"], sort=False)["factor"]
             .last().reset_index())
    return daily[["date", "instrument", "factor"]]


def daily_forward_return(df_30m: pd.DataFrame) -> pd.DataFrame:
    """从 30m 数据计算日频 forward return。

    每日收盘 = 当日最后一根 30m bar 的 close；
    ret_fwd = next_day_close / today_close - 1。
    返回 (date, instrument, ret_fwd)。
    """
    temp = df_30m[["date", "instrument", "close"]].copy()
    temp["timestamp"] = pd.to_datetime(temp["date"])
    temp["date"] = temp["timestamp"].dt.normalize()
    daily_close = (temp.sort_values(["instrument", "timestamp"], kind="mergesort")
                   .groupby(["date", "instrument"], sort=False)["close"]
                   .last().reset_index()
                   .sort_values(["instrument", "date"], kind="mergesort"))
    next_close = daily_close.groupby("instrument")["close"].shift(-1)
    daily_close["ret_fwd"] = next_close / daily_close["close"] - 1.0
    return daily_close[["date", "instrument", "ret_fwd"]]
