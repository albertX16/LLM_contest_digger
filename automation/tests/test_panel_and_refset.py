from __future__ import annotations

import pandas as pd
import pytest

from automation.evaluate.barra import build_local_classic_exposures, load_barra_exposures
from automation.evaluate.refset import build_default_refset
from automation.panel.fetch import (
    _covers_requested_range,
    _has_monthly_continuity,
    _is_intraday_frame,
    _quarter_ranges,
    daily_forward_return,
)


def test_mislabelled_partial_cache_is_rejected() -> None:
    partial = pd.DataFrame({"date": pd.date_range("2023-01-03", "2023-12-29", freq="D")})
    assert not _covers_requested_range(partial, "2019-01-01", "2023-12-31")
    assert _covers_requested_range(partial, "2023-01-01", "2023-12-31")
    assert not _is_intraday_frame(partial)
    intraday = partial.copy()
    intraday["date"] = intraday["date"] + pd.Timedelta(hours=10)
    assert _is_intraday_frame(intraday)
    assert _has_monthly_continuity(intraday, "2023-01-01", "2023-12-31")
    assert not _has_monthly_continuity(intraday[intraday.date.dt.month != 6],
                                       "2023-01-01", "2023-12-31")
    assert _quarter_ranges("2019-06-05", "2020-01-02") == [
        ("2019-06-05", "2019-06-30"),
        ("2019-07-01", "2019-09-30"),
        ("2019-10-01", "2019-12-31"),
        ("2020-01-01", "2020-01-02"),
    ]


def test_forward_return_never_shifts_across_instruments() -> None:
    frame = pd.DataFrame({
        "date": pd.to_datetime([
            "2023-01-02 10:00", "2023-01-02 15:00", "2023-01-03 15:00",
            "2023-01-02 15:00", "2023-01-03 15:00",
        ]),
        "instrument": ["A", "A", "A", "B", "B"],
        "close": [9.0, 10.0, 11.0, 100.0, 90.0],
    })
    result = daily_forward_return(frame)
    a_first = result[(result.instrument == "A") & (result.date == pd.Timestamp("2023-01-02"))]
    b_first = result[(result.instrument == "B") & (result.date == pd.Timestamp("2023-01-02"))]
    assert a_first.ret_fwd.iloc[0] == pytest.approx(0.1)
    assert b_first.ret_fwd.iloc[0] == pytest.approx(-0.1)
    assert result.groupby("instrument").tail(1).ret_fwd.isna().all()


def test_default_refset_is_nonempty_and_date_aligned() -> None:
    rows = []
    for date in pd.bdate_range("2023-01-02", periods=25):
        for minute in ("10:00", "15:00"):
            for i in range(12):
                close = 100 + i + (date.dayofyear / 100)
                rows.append({
                    "date": pd.Timestamp(f"{date.date()} {minute}"),
                    "instrument": f"S{i:02d}", "close": close,
                    "volume": 100 + i, "amount": close * (100 + i),
                    "deal_number": 10 + i, "bid_volume1": 30 + i,
                    "ask_volume1": 20 + i, "bid_price1": close - .1,
                    "ask_price1": close + .1,
                })
    refs = build_default_refset(pd.DataFrame(rows))
    assert len(refs) == 8
    assert all(isinstance(index, pd.DatetimeIndex) for index in (x.index for x in refs.values()))
    controls = build_local_classic_exposures(pd.DataFrame(rows), beta_window=10,
                                             min_periods=5)
    assert set(controls) == {
        "LOCAL_SIZE_PROXY", "LOCAL_BETA_60D", "LOCAL_MOMENTUM_20D",
        "LOCAL_REVERSAL_5D", "LOCAL_RESVOL_20D", "LOCAL_SIZENL_PROXY",
        "LOCAL_ILLIQUIDITY_20D", "LOCAL_PRICE_LEVEL", "LOCAL_VOLUME_20D",
    }


def test_official_barra_mode_never_substitutes_a_proxy(tmp_path) -> None:
    missing = tmp_path / "official_exposure.parquet"
    with pytest.raises(FileNotFoundError, match="不会用价格/成交量代理"):
        load_barra_exposures(missing, "2023-01-01", "2023-12-31")
