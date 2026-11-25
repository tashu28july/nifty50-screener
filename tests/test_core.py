"""
Run with:  python -m pytest -q
Uses synthetic price data, so no internet is needed.
"""

import os
import sys
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from data_fetcher import clean_price_frame, drop_incomplete_bar, to_weekly  # noqa: E402
from indicators import add_daily_indicators, rsi  # noqa: E402
from levels import cluster_levels, fib_pivots  # noqa: E402
from strategy import LONG, NEUTRAL, SHORT, analyse_stock, choose_expiry, option_idea  # noqa: E402

NOW = datetime(2026, 11, 25, 18, 0, tzinfo=config.IST)


def make_prices(drift: float, n: int = 400, seed: int = 1, start: float = 1000.0) -> pd.DataFrame:
    """Random-walk OHLCV with a given daily drift (e.g. 0.003 = uptrend)."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end="2026-11-24", periods=n)
    close = start * np.exp(np.cumsum(drift + rng.normal(0, 0.012, n)))
    open_ = close * (1 + rng.normal(0, 0.004, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, n)))
    vol = rng.integers(1_000_000, 3_000_000, n).astype(float)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol}, index=idx)


def run(df, **kw):
    return analyse_stock("TEST", df, nifty=None, regime={"available": False, "bullish": None},
                         today=date(2026, 11, 25), now=NOW, **kw)


def test_rsi_bounds():
    values = rsi(make_prices(0.002)["Close"]).dropna()
    assert values.between(0, 100).all()


def test_uptrend_gives_valid_long_plan():
    s = run(make_prices(0.004))
    assert s.bias == LONG
    assert s.stop_loss < s.entry < s.target1 < s.target2
    assert s.rr_t1 >= config.T1_MIN_R - 0.05
    assert s.equity_qty > 0
    assert "CE" in s.option_idea


def test_downtrend_gives_valid_short_plan():
    s = run(make_prices(-0.004))
    assert s.bias == SHORT
    assert s.target2 < s.target1 < s.entry < s.stop_loss
    assert s.equity_qty == 0          # no overnight shorting in cash
    assert "PE" in s.option_idea


def test_stop_distance_within_atr_limits():
    s = run(make_prices(0.004))
    atr_value = s.indicators["ATR"]
    dist = s.entry - s.stop_loss
    assert config.SL_ATR_MIN * atr_value - 0.1 <= dist <= config.SL_ATR_MAX * atr_value + 0.1


def test_position_size_respects_risk_and_capital():
    s = run(make_prices(0.004), capital=100000, risk_pct=1.0)
    assert s.equity_qty * s.risk_per_share <= 1000 + 1e-6
    assert s.equity_qty * s.entry <= 100000


def test_flat_market_is_neutral_with_high_threshold():
    s = run(make_prices(0.0, seed=7), min_score=95)
    assert s.bias == NEUTRAL and s.entry is None
    assert s.analysis                          # analysis is still produced


def test_short_history_raises():
    with pytest.raises(ValueError):
        run(make_prices(0.003, n=100))


def test_none_data_raises():
    with pytest.raises(ValueError):
        run(None)


def test_fib_pivots_ordering():
    p = fib_pivots(110, 90, 100)
    assert p.s3 < p.s2 < p.s1 < p.pivot < p.r1 < p.r2 < p.r3


def test_cluster_levels_merges_close_prices():
    assert len(cluster_levels([100, 100.5, 120])) == 2
    assert cluster_levels([]) == []


def test_expiry_rolls_to_next_month():
    assert choose_expiry(date(2026, 11, 2)) == date(2026, 11, 24)    # last Tue of Nov
    assert choose_expiry(date(2026, 11, 20)) == date(2026, 12, 29)   # too close -> Dec
    assert choose_expiry(date(2026, 12, 25)) == date(2027, 1, 26)    # year rollover


def test_option_idea_neutral():
    assert option_idea("X", NEUTRAL, 1000, date(2026, 11, 1)) == "-"


def test_drop_incomplete_bar():
    df = make_prices(0.001, n=5)
    df.index = pd.bdate_range(end="2026-11-25", periods=5)
    during = datetime(2026, 11, 25, 11, 0, tzinfo=config.IST)
    after = datetime(2026, 11, 25, 16, 0, tzinfo=config.IST)
    assert len(drop_incomplete_bar(df, during)) == 4
    assert len(drop_incomplete_bar(df, after)) == 5


def test_clean_frame_handles_bad_input():
    assert clean_price_frame(None).empty
    assert clean_price_frame(pd.DataFrame({"Close": [1, 2]})).empty
    df = make_prices(0.001, n=10)
    df.iloc[3, df.columns.get_loc("Close")] = np.nan
    assert len(clean_price_frame(df)) == 9


def test_weekly_resample():
    w = to_weekly(make_prices(0.001, n=50))
    assert (w.index.dayofweek == 4).all()
    assert w["High"].ge(w["Low"]).all()


def test_indicator_columns_present():
    d = add_daily_indicators(make_prices(0.002))
    for col in ["EMA20", "EMA50", "SMA200", "RSI", "ATR", "ADX", "MACD_HIST", "VOL_AVG"]:
        assert col in d.columns
