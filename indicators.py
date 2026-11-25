"""
indicators.py
-------------
Technical indicators written with plain pandas (no extra libraries), so
you can read exactly how each one is calculated.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average."""
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple moving average."""
    return series.rolling(period, min_periods=period).mean()


def _wilder(series: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing (used by RSI, ATR, ADX)."""
    return series.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int = config.RSI_PERIOD) -> pd.Series:
    """Relative Strength Index (0-100)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = _wilder(gain, period)
    avg_loss = _wilder(loss, period)

    rs = avg_gain / avg_loss.replace(0, np.nan)
    value = 100 - 100 / (1 + rs)
    # No losses at all -> RSI is 100 (keep NaN during warm-up)
    return value.mask((avg_loss == 0) & avg_gain.notna(), 100.0)


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["Close"].shift(1)
    ranges = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(df: pd.DataFrame, period: int = config.ATR_PERIOD) -> pd.Series:
    """Average True Range - the stock's typical daily move in rupees."""
    return _wilder(true_range(df), period)


def macd(close: pd.Series):
    """Returns (macd_line, signal_line, histogram)."""
    line = ema(close, config.MACD_FAST) - ema(close, config.MACD_SLOW)
    signal = line.ewm(span=config.MACD_SIGNAL, adjust=False).mean()
    return line, signal, line - signal


def adx(df: pd.DataFrame, period: int = config.ADX_PERIOD):
    """Returns (adx, plus_di, minus_di). ADX > 20-25 = trending market."""
    up_move = df["High"].diff()
    down_move = -df["Low"].diff()

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index
    )

    atr_values = _wilder(true_range(df), period).replace(0, np.nan)
    plus_di = 100 * _wilder(plus_dm, period) / atr_values
    minus_di = 100 * _wilder(minus_dm, period) / atr_values

    di_sum = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / di_sum
    return _wilder(dx, period), plus_di, minus_di


def add_daily_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of the daily frame with all indicator columns added."""
    out = df.copy()
    close = out["Close"]

    out["EMA20"] = ema(close, config.EMA_FAST)
    out["EMA50"] = ema(close, config.EMA_MID)
    out["SMA200"] = sma(close, config.SMA_SLOW)
    out["RSI"] = rsi(close)
    out["ATR"] = atr(out)
    out["MACD"], out["MACD_SIGNAL"], out["MACD_HIST"] = macd(close)
    out["ADX"], out["PLUS_DI"], out["MINUS_DI"] = adx(out)
    # Average of the PREVIOUS 20 days, so today's volume is compared fairly
    out["VOL_AVG"] = out["Volume"].rolling(config.VOLUME_AVG_PERIOD).mean().shift(1)
    return out


def add_weekly_indicators(weekly: pd.DataFrame) -> pd.DataFrame:
    out = weekly.copy()
    out["WEMA_FAST"] = ema(out["Close"], config.WEEKLY_EMA_FAST)
    out["WEMA_SLOW"] = ema(out["Close"], config.WEEKLY_EMA_SLOW)
    out["WRSI"] = rsi(out["Close"])
    return out
