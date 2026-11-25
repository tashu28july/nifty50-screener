"""
levels.py
---------
Support / resistance, Fibonacci pivots and Fibonacci retracements.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

import config


@dataclass
class FibPivots:
    pivot: float
    r1: float
    r2: float
    r3: float
    s1: float
    s2: float
    s3: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


def fib_pivots(high: float, low: float, close: float) -> FibPivots:
    """Fibonacci pivot points from the previous period's high/low/close."""
    pivot = (high + low + close) / 3
    rng = high - low
    return FibPivots(
        pivot=pivot,
        r1=pivot + 0.382 * rng,
        r2=pivot + 0.618 * rng,
        r3=pivot + 1.000 * rng,
        s1=pivot - 0.382 * rng,
        s2=pivot - 0.618 * rng,
        s3=pivot - 1.000 * rng,
    )


def swing_points(df: pd.DataFrame, window: int = config.SWING_WINDOW):
    """
    A swing high is a bar whose High is the highest of `window` bars on both
    sides (a swing low is the mirror). Returns (list_of_highs, list_of_lows).
    """
    if len(df) < 2 * window + 1:
        return [], []
    span = 2 * window + 1
    roll_max = df["High"].rolling(span, center=True).max()
    roll_min = df["Low"].rolling(span, center=True).min()
    highs = df.loc[df["High"] == roll_max, "High"].tolist()
    lows = df.loc[df["Low"] == roll_min, "Low"].tolist()
    return highs, lows


def cluster_levels(prices: list[float], tolerance_pct: float = config.SR_CLUSTER_PCT):
    """
    Merge prices that are within `tolerance_pct` % of each other.
    Returns a list of (level, touches) sorted by price.
    """
    if not prices:
        return []
    clusters: list[list[float]] = []
    for price in sorted(prices):
        if clusters and abs(price - clusters[-1][-1]) / clusters[-1][-1] * 100 <= tolerance_pct:
            clusters[-1].append(price)
        else:
            clusters.append([price])
    return [(sum(c) / len(c), len(c)) for c in clusters]


def support_resistance(df: pd.DataFrame, close: float, lookback: int = config.SR_LOOKBACK):
    """
    Returns (supports, resistances): lists of (price, touches).
    Supports are below the close (nearest first), resistances above it.
    """
    recent = df.tail(lookback)
    highs, lows = swing_points(recent)
    levels = cluster_levels(highs + lows)
    supports = sorted([lv for lv in levels if lv[0] < close], key=lambda x: -x[0])
    resistances = sorted([lv for lv in levels if lv[0] > close], key=lambda x: x[0])
    return supports, resistances


def fib_retracement(df: pd.DataFrame, lookback: int = config.FIB_SWING_LOOKBACK) -> dict:
    """
    Fibonacci retracement of the biggest swing in the last `lookback` bars.
    If the high came after the low the swing is UP (levels act as support),
    otherwise DOWN (levels act as resistance).
    """
    recent = df.tail(lookback)
    if recent.empty:
        return {}
    high_idx, low_idx = recent["High"].idxmax(), recent["Low"].idxmin()
    swing_high, swing_low = float(recent.loc[high_idx, "High"]), float(recent.loc[low_idx, "Low"])
    rng = swing_high - swing_low
    if rng <= 0:
        return {}

    direction = "UP" if high_idx > low_idx else "DOWN"
    ratios = (0.236, 0.382, 0.5, 0.618, 0.786)
    if direction == "UP":
        levels = {f"{r:.3f}": swing_high - r * rng for r in ratios}
    else:
        levels = {f"{r:.3f}": swing_low + r * rng for r in ratios}
    return {
        "direction": direction,
        "swing_high": swing_high,
        "swing_low": swing_low,
        "levels": levels,
    }
