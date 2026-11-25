"""
strategy.py
-----------
Scores each stock, decides LONG / SHORT / NEUTRAL, and builds the trade
plan (entry, stop-loss, targets, instrument) plus a written analysis.

Score range: -100 (strong bearish) ... +100 (strong bullish)
"""

from __future__ import annotations

import calendar
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import pandas as pd

import config
from data_fetcher import to_weekly
from indicators import add_daily_indicators, add_weekly_indicators
from levels import fib_pivots, fib_retracement, support_resistance

LONG, SHORT, NEUTRAL = "LONG", "SHORT", "NEUTRAL"


# ---------------------------------------------------------------------------
# Result object
# ---------------------------------------------------------------------------
@dataclass
class TradeSetup:
    symbol: str
    close: float
    change_pct: float
    score: int
    bias: str
    setup_type: str = "No setup"
    entry_type: str = ""
    entry: float | None = None
    stop_loss: float | None = None
    target1: float | None = None
    target2: float | None = None
    risk_per_share: float | None = None
    rr_t1: float | None = None
    rr_t2: float | None = None
    equity_qty: int = 0
    instrument: str = "-"
    option_idea: str = "-"
    score_breakdown: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    analysis: list[str] = field(default_factory=list)
    indicators: dict = field(default_factory=dict)
    levels: dict = field(default_factory=dict)

    def to_row(self) -> dict:
        """Flat dictionary for tables / CSV export."""
        return {
            "Symbol": self.symbol,
            "Bias": self.bias,
            "Score": self.score,
            "Setup": self.setup_type,
            "Close": self.close,
            "Chg %": round(self.change_pct, 2),
            "Entry": self.entry,
            "Trigger": self.entry_type,
            "Stop Loss": self.stop_loss,
            "Target 1": self.target1,
            "Target 2": self.target2,
            "Risk/Share": self.risk_per_share,
            "R:R T1": self.rr_t1,
            "R:R T2": self.rr_t2,
            "Equity Qty": self.equity_qty,
            "Instrument": self.instrument,
            "RSI": self.indicators.get("RSI"),
            "ADX": self.indicators.get("ADX"),
            "Vol x Avg": self.indicators.get("VolRatio"),
        }


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def round_tick(price: float, tick: float = config.TICK_SIZE) -> float:
    return round(round(price / tick) * tick, 2)


def _safe(value, default=float("nan")) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(value) else value


def completed_week_bar(weekly: pd.DataFrame, now: datetime | None = None) -> pd.Series:
    """Last FINISHED weekly candle (weekly pivots must use a closed week)."""
    now = now or datetime.now(config.IST)
    week_end = weekly.index[-1].date()               # Friday label
    week_closed = datetime.combine(week_end, config.MARKET_CLOSE, tzinfo=config.IST)
    if now >= week_closed or len(weekly) < 2:
        return weekly.iloc[-1]
    return weekly.iloc[-2]


def market_regime(nifty: pd.DataFrame | None) -> dict:
    """Is the Nifty 50 index itself trending up or down?"""
    if nifty is None or len(nifty) < config.EMA_MID + 5:
        return {"available": False, "bullish": None}
    d = add_daily_indicators(nifty)
    last, prev = d.iloc[-1], d.iloc[-2]
    bullish = bool(last["Close"] > last["EMA50"] and last["EMA20"] > last["EMA50"])
    bearish = bool(last["Close"] < last["EMA50"] and last["EMA20"] < last["EMA50"])
    return {
        "available": True,
        "bullish": True if bullish else (False if bearish else None),
        "close": float(last["Close"]),
        "change_pct": float((last["Close"] / prev["Close"] - 1) * 100),
        "ema20": float(last["EMA20"]),
        "ema50": float(last["EMA50"]),
        "sma200": _safe(last["SMA200"]),
        "rsi": _safe(last["RSI"]),
        "date": d.index[-1].date(),
    }


# ---------------------------------------------------------------------------
# Options helpers
# ---------------------------------------------------------------------------
def strike_step(price: float) -> float:
    """Approximate NSE stock-option strike interval. ALWAYS verify on the chain."""
    if price < 250:
        return 2.5
    if price < 500:
        return 5
    if price < 1000:
        return 10
    if price < 2500:
        return 20
    if price < 5000:
        return 50
    if price < 10000:
        return 100
    return 250


def last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    day = date(year, month, calendar.monthrange(year, month)[1])
    while day.weekday() != weekday:
        day -= timedelta(days=1)
    return day


def choose_expiry(today: date) -> date:
    """Current-month expiry, or next month if too few days are left."""
    expiry = last_weekday_of_month(today.year, today.month, config.STOCK_EXPIRY_WEEKDAY)
    if (expiry - today).days < config.ROLL_TO_NEXT_MONTH_DAYS:
        year = today.year + (today.month == 12)
        month = 1 if today.month == 12 else today.month + 1
        expiry = last_weekday_of_month(year, month, config.STOCK_EXPIRY_WEEKDAY)
    return expiry


def option_idea(symbol: str, bias: str, spot: float, today: date) -> str:
    if bias not in (LONG, SHORT):
        return "-"
    step = strike_step(spot)
    atm = round(spot / step) * step
    expiry = choose_expiry(today)
    if bias == LONG:
        itm, kind = math.floor(spot / step) * step, "CE"
        if itm == atm:
            itm -= step
    else:
        itm, kind = math.ceil(spot / step) * step, "PE"
        if itm == atm:
            itm += step
    fmt = lambda x: f"{x:g}"
    return (
        f"Buy {symbol} {expiry:%d-%b-%Y} {fmt(itm)} {kind} (1 strike ITM) "
        f"or {fmt(atm)} {kind} (ATM). Strike gap ~{fmt(step)} - verify on the "
        f"option chain. Exit the option when the STOCK hits the SL / targets."
    )


def instrument_for(bias: str, score: int, adx_value: float) -> str:
    strong = abs(score) >= config.FUTURES_MIN_SCORE and adx_value >= config.FUTURES_MIN_ADX
    if bias == LONG:
        return "Futures long / Equity (high conviction)" if strong else "Equity delivery or ITM Call"
    if bias == SHORT:
        return "Futures short / Buy Put (high conviction)" if strong else "Buy Put (defined risk)"
    return "-"


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
class _Scorer:
    """Collects score points together with the reason for each."""

    def __init__(self):
        self.total = 0.0
        self.lines: list[str] = []

    def add(self, points: float, reason: str):
        if points == 0:
            return
        self.total += points
        sign = "+" if points > 0 else ""
        self.lines.append(f"{sign}{points:g}  {reason}")


def _score_stock(d, w, nifty_close, regime, signals) -> tuple[int, list[str], list[str]]:
    s = _Scorer()
    warnings: list[str] = []
    last, prev = d.iloc[-1], d.iloc[-2]
    close = last["Close"]

    # 1) Daily trend structure (max +/-25)
    s.add(5 if close > last["EMA20"] else -5, "Close vs 20 EMA")
    s.add(5 if last["EMA20"] > last["EMA50"] else -5, "20 EMA vs 50 EMA")
    s.add(5 if last["EMA50"] > last["SMA200"] else -5, "50 EMA vs 200 SMA")
    s.add(5 if close > last["SMA200"] else -5, "Close vs 200 SMA")
    ema20_slope = last["EMA20"] - d["EMA20"].iloc[-6]
    s.add(5 if ema20_slope > 0 else -5, "20 EMA slope (5 days)")

    # 2) Weekly trend (max +/-15)
    wl = w.iloc[-1]
    if pd.notna(wl.get("WEMA_SLOW")):
        s.add(8 if wl["Close"] > wl["WEMA_SLOW"] else -8, "Weekly close vs weekly 20 EMA")
        s.add(7 if wl["WEMA_FAST"] > wl["WEMA_SLOW"] else -7, "Weekly 10 EMA vs 20 EMA")

    # 3) Momentum: RSI and MACD (max +/-15)
    r = last["RSI"]
    if 55 <= r < 70:
        s.add(8, f"RSI {r:.0f} in bullish zone")
    elif 70 <= r < 78:
        s.add(4, f"RSI {r:.0f} strong but stretched")
    elif r >= 78:
        s.add(-2, f"RSI {r:.0f} overbought")
        warnings.append(f"RSI {r:.0f} is overbought - wait for a dip or use a smaller size.")
    elif 30 < r <= 45:
        s.add(-8, f"RSI {r:.0f} in bearish zone")
    elif 22 < r <= 30:
        s.add(-4, f"RSI {r:.0f} weak but stretched")
    elif r <= 22:
        s.add(2, f"RSI {r:.0f} oversold")
        warnings.append(f"RSI {r:.0f} is oversold - short-covering bounce risk.")

    hist, prev_hist = last["MACD_HIST"], prev["MACD_HIST"]
    if hist > 0:
        s.add(7 if hist > prev_hist else 3, "MACD histogram positive" + (" and rising" if hist > prev_hist else ""))
    else:
        s.add(-7 if hist < prev_hist else -3, "MACD histogram negative" + (" and falling" if hist < prev_hist else ""))

    # 4) Price action (max +/-23)
    if signals["breakout"]:
        s.add(20 if signals["volume_ok"] else 10,
              f"{config.BREAKOUT_LOOKBACK}-day breakout" + (" with volume" if signals["volume_ok"] else " (low volume)"))
    elif signals["breakdown"]:
        s.add(-20 if signals["volume_ok"] else -10,
              f"{config.BREAKOUT_LOOKBACK}-day breakdown" + (" with volume" if signals["volume_ok"] else " (low volume)"))
    elif signals["pullback_long"]:
        s.add(12, "Pullback to 20 EMA in uptrend, bullish candle")
    elif signals["pullback_short"]:
        s.add(-12, "Pullback to 20 EMA in downtrend, bearish candle")

    rng = last["High"] - last["Low"]
    if rng > 0:
        pos = (close - last["Low"]) / rng
        if pos >= 0.75:
            s.add(3, "Closed near day's high")
        elif pos <= 0.25:
            s.add(-3, "Closed near day's low")

    # 5) Weekly Fibonacci pivot position (max +/-10)
    piv = signals["pivots"]
    s.add(5 if close > piv.pivot else -5, "Close vs weekly pivot")
    if close > piv.r1:
        s.add(5, "Above weekly R1")
    elif close < piv.s1:
        s.add(-5, "Below weekly S1")

    # 6) Relative strength vs Nifty (max +/-10)
    if nifty_close is not None:
        n = config.RS_LOOKBACK
        aligned = nifty_close.reindex(d.index).ffill()
        stock_ret = close / d["Close"].iloc[-n - 1] - 1
        nifty_ret = aligned.iloc[-1] / aligned.iloc[-n - 1] - 1
        if pd.notna(nifty_ret):
            rs = (stock_ret - nifty_ret) * 100
            signals["rs"] = rs
            if rs > 3:
                s.add(10, f"Outperforming Nifty by {rs:.1f}% ({n}d)")
            elif rs > 0:
                s.add(5, f"Slightly outperforming Nifty ({rs:+.1f}%)")
            elif rs < -3:
                s.add(-10, f"Underperforming Nifty by {abs(rs):.1f}% ({n}d)")
            else:
                s.add(-5, f"Slightly underperforming Nifty ({rs:+.1f}%)")

    # 7) Market regime (max +/-5)
    if regime.get("bullish") is True:
        s.add(5, "Nifty in uptrend")
    elif regime.get("bullish") is False:
        s.add(-5, "Nifty in downtrend")

    total = s.total
    # 8) Choppy-market filter
    if last["ADX"] < config.CHOPPY_ADX:
        total *= config.CHOPPY_PENALTY
        s.lines.append(f"x{config.CHOPPY_PENALTY}  ADX {last['ADX']:.0f} < {config.CHOPPY_ADX} (sideways, score reduced)")
        warnings.append("ADX is low - stock is range-bound, breakouts often fail.")

    return int(round(max(-100, min(100, total)))), s.lines, warnings


# ---------------------------------------------------------------------------
# Trade plan
# ---------------------------------------------------------------------------
def _pick_targets(entry: float, risk: float, candidates: list[float], direction: int):
    """
    direction = +1 for long, -1 for short.
    T1: first real level between 1.5R and 3R away, else exactly 1.5R.
    T2: first level beyond max(T1 + 0.5R, 2.5R) and within 5R, else 3R.
    """
    def dist(level):
        return (level - entry) * direction

    ahead = sorted([c for c in candidates if dist(c) > 0], key=dist)

    t1 = next((c for c in ahead if config.T1_MIN_R * risk <= dist(c) <= config.T1_MAX_R * risk), None)
    if t1 is None:
        t1 = entry + direction * config.T1_MIN_R * risk

    t2_min = max(dist(t1) + 0.5 * risk, config.T2_MIN_R * risk)
    t2 = next((c for c in ahead if t2_min <= dist(c) <= config.T2_MAX_R * risk), None)
    if t2 is None:
        t2 = entry + direction * max(config.T2_DEFAULT_R * risk, t2_min)

    blockers = [c for c in ahead if dist(c) < 1.0 * risk]
    return t1, t2, blockers


def _build_plan(setup: TradeSetup, d: pd.DataFrame, candidates: list[float],
                capital: float, risk_pct: float, signals: dict):
    last = d.iloc[-1]
    atr_value = last["ATR"]
    direction = 1 if setup.bias == LONG else -1

    if setup.bias == LONG:
        entry = last["High"]
        swing = d["Low"].tail(3).min() - config.SL_ATR_BUFFER * atr_value
        stop = min(max(swing, entry - config.SL_ATR_MAX * atr_value), entry - config.SL_ATR_MIN * atr_value)
        setup.entry_type = "Buy above"
        setup.setup_type = ("Breakout" if signals["breakout"]
                            else "Pullback buy" if signals["pullback_long"] else "Trend continuation")
    else:
        entry = last["Low"]
        swing = d["High"].tail(3).max() + config.SL_ATR_BUFFER * atr_value
        stop = max(min(swing, entry + config.SL_ATR_MAX * atr_value), entry + config.SL_ATR_MIN * atr_value)
        setup.entry_type = "Sell below"
        setup.setup_type = ("Breakdown" if signals["breakdown"]
                            else "Pullback sell" if signals["pullback_short"] else "Downtrend continuation")

    risk = abs(entry - stop)
    if risk <= 0 or math.isnan(risk):
        setup.warnings.append("Could not compute a valid stop-loss.")
        return

    t1, t2, blockers = _pick_targets(entry, risk, candidates, direction)

    setup.entry = round_tick(entry)
    setup.stop_loss = round_tick(stop)
    setup.target1 = round_tick(t1)
    setup.target2 = round_tick(t2)
    setup.risk_per_share = round(abs(setup.entry - setup.stop_loss), 2)
    if setup.risk_per_share > 0:
        setup.rr_t1 = round(abs(setup.target1 - setup.entry) / setup.risk_per_share, 2)
        setup.rr_t2 = round(abs(setup.target2 - setup.entry) / setup.risk_per_share, 2)

    # Position size for cash equity (longs only - no overnight shorting in cash)
    if setup.bias == LONG and setup.risk_per_share > 0 and capital > 0:
        risk_amount = capital * risk_pct / 100
        qty_by_risk = int(risk_amount // setup.risk_per_share)
        qty_by_capital = int(capital // setup.entry)
        setup.equity_qty = max(0, min(qty_by_risk, qty_by_capital))

    for level in blockers:
        word = "Resistance" if setup.bias == LONG else "Support"
        setup.warnings.append(f"{word} at {level:,.2f} is less than 1R away - may slow the move; consider booking part there.")
    if abs(entry - last["Close"]) > atr_value:
        setup.warnings.append("Trigger is more than 1 ATR away from close (long wick) - wait for confirmation.")


# ---------------------------------------------------------------------------
# Written analysis
# ---------------------------------------------------------------------------
def _trend_word(close, ema20, ema50, sma200) -> str:
    if close > ema20 > ema50 > sma200:
        return "Strong uptrend (price > 20 EMA > 50 EMA > 200 SMA)"
    if close < ema20 < ema50 < sma200:
        return "Strong downtrend (price < 20 EMA < 50 EMA < 200 SMA)"
    if close > sma200:
        return "Above 200 SMA - long-term up, short-term mixed"
    return "Below 200 SMA - long-term down, short-term mixed"


def _build_analysis(setup, d, w, signals, pivots, supports, resistances, fib) -> list[str]:
    last = d.iloc[-1]
    wl = w.iloc[-1]
    f = lambda x: f"{x:,.2f}"
    lines = [
        f"**Daily trend:** {_trend_word(last['Close'], last['EMA20'], last['EMA50'], last['SMA200'])}.",
        f"**Moving averages:** 20 EMA {f(last['EMA20'])} | 50 EMA {f(last['EMA50'])} | 200 SMA {f(last['SMA200'])}.",
    ]
    if pd.notna(wl.get("WEMA_SLOW")):
        weekly_state = "bullish" if wl["Close"] > wl["WEMA_SLOW"] and wl["WEMA_FAST"] > wl["WEMA_SLOW"] else \
                       "bearish" if wl["Close"] < wl["WEMA_SLOW"] and wl["WEMA_FAST"] < wl["WEMA_SLOW"] else "mixed"
        lines.append(f"**Weekly trend:** {weekly_state} - weekly close {f(wl['Close'])} vs weekly 10/20 EMA "
                     f"{f(wl['WEMA_FAST'])} / {f(wl['WEMA_SLOW'])}; weekly RSI {_safe(wl.get('WRSI')):.0f}.")

    lines.append(f"**Momentum:** RSI {last['RSI']:.1f}; MACD {last['MACD']:.2f} vs signal {last['MACD_SIGNAL']:.2f} "
                 f"(histogram {'positive' if last['MACD_HIST'] > 0 else 'negative'}).")
    lines.append(f"**Trend strength:** ADX {last['ADX']:.1f} (+DI {last['PLUS_DI']:.1f} / -DI {last['MINUS_DI']:.1f}) - "
                 + ("trending." if last["ADX"] >= 25 else "moderate." if last["ADX"] >= config.CHOPPY_ADX else "weak / sideways."))
    lines.append(f"**Volatility:** ATR {f(last['ATR'])} (~{last['ATR'] / last['Close'] * 100:.1f}% of price per day).")

    vr = signals["vol_ratio"]
    lines.append(f"**Volume:** {vr:.2f}x the 20-day average." if not math.isnan(vr) else "**Volume:** not available.")

    if signals["breakout"]:
        pa = f"Closed above the {config.BREAKOUT_LOOKBACK}-day high {f(signals['prior_high'])} - breakout."
    elif signals["breakdown"]:
        pa = f"Closed below the {config.BREAKOUT_LOOKBACK}-day low {f(signals['prior_low'])} - breakdown."
    elif signals["pullback_long"]:
        pa = "Dipped to the 20 EMA and closed green - pullback buy in an uptrend."
    elif signals["pullback_short"]:
        pa = "Rallied to the 20 EMA and closed red - pullback sell in a downtrend."
    else:
        pa = (f"Inside the {config.BREAKOUT_LOOKBACK}-day range {f(signals['prior_low'])} - "
              f"{f(signals['prior_high'])}; no fresh trigger.")
    lines.append(f"**Price action:** {pa}")

    lines.append("**Weekly Fibonacci pivots:** "
                 f"S3 {f(pivots.s3)} | S2 {f(pivots.s2)} | S1 {f(pivots.s1)} | **P {f(pivots.pivot)}** | "
                 f"R1 {f(pivots.r1)} | R2 {f(pivots.r2)} | R3 {f(pivots.r3)}.")

    if fib:
        fl = " | ".join(f"{k} {f(v)}" for k, v in fib["levels"].items())
        lines.append(f"**Fibonacci retracement** ({fib['direction']} swing {f(fib['swing_low'])} -> "
                     f"{f(fib['swing_high'])}, last {config.FIB_SWING_LOOKBACK} days): {fl}.")

    sup = ", ".join(f"{f(p)} ({t}x)" for p, t in supports[:3]) or "none nearby"
    res = ", ".join(f"{f(p)} ({t}x)" for p, t in resistances[:3]) or "none nearby (near highs)"
    lines.append(f"**Support (swing levels):** {sup}.")
    lines.append(f"**Resistance (swing levels):** {res}.")
    lines.append(f"**52-week range:** {f(signals['low_52w'])} - {f(signals['high_52w'])}.")

    if "rs" in signals:
        lines.append(f"**Relative strength vs Nifty ({config.RS_LOOKBACK}d):** {signals['rs']:+.1f}%.")

    if setup.bias == NEUTRAL:
        lines.append("**Verdict:** No clear edge - stay out or wait for a breakout above resistance / "
                     "breakdown below support.")
    else:
        lines.append(f"**Verdict:** {setup.bias} ({setup.setup_type}). {setup.entry_type} {f(setup.entry)}, "
                     f"SL {f(setup.stop_loss)}, T1 {f(setup.target1)}, T2 {f(setup.target2)}. "
                     "Book ~50% at T1 and trail the stop to entry for the rest.")
    return lines


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
REQUIRED_COLUMNS = ["EMA20", "EMA50", "SMA200", "RSI", "ATR", "MACD_HIST", "ADX"]


def analyse_stock(
    symbol: str,
    daily: pd.DataFrame,
    nifty: pd.DataFrame | None = None,
    regime: dict | None = None,
    capital: float = 100000,
    risk_pct: float = 1.0,
    min_score: int = config.DEFAULT_MIN_SCORE,
    today: date | None = None,
    now: datetime | None = None,
) -> TradeSetup:
    """Full analysis of one stock. Raises ValueError if data is insufficient."""
    if daily is None or len(daily) < config.MIN_BARS:
        raise ValueError(f"{symbol}: need at least {config.MIN_BARS} daily bars")

    d = add_daily_indicators(daily)
    w = add_weekly_indicators(to_weekly(daily))
    last, prev = d.iloc[-1], d.iloc[-2]
    if last[REQUIRED_COLUMNS].isna().any() or len(w) < 3:
        raise ValueError(f"{symbol}: indicators not ready (data gaps)")
    if last["ATR"] <= 0:
        raise ValueError(f"{symbol}: ATR is zero (no price movement)")

    regime = regime if regime is not None else market_regime(nifty)
    today = today or datetime.now(config.IST).date()
    close = float(last["Close"])

    # --- Price-action signals -------------------------------------------
    lb = config.BREAKOUT_LOOKBACK
    prior_high = d["High"].iloc[-lb - 1:-1].max()
    prior_low = d["Low"].iloc[-lb - 1:-1].min()
    vol_ratio = _safe(last["Volume"] / last["VOL_AVG"]) if _safe(last["VOL_AVG"], 0) > 0 else float("nan")
    uptrend = last["EMA20"] > last["EMA50"] > last["SMA200"]
    downtrend = last["EMA20"] < last["EMA50"] < last["SMA200"]

    week = completed_week_bar(to_weekly(daily), now)
    pivots = fib_pivots(week["High"], week["Low"], week["Close"])

    signals = {
        "prior_high": prior_high,
        "prior_low": prior_low,
        "vol_ratio": vol_ratio,
        "volume_ok": (not math.isnan(vol_ratio)) and vol_ratio >= config.VOLUME_SURGE_MULT,
        "breakout": close > prior_high,
        "breakdown": close < prior_low,
        "pullback_long": bool(uptrend and last["Low"] <= last["EMA20"] * 1.01
                              and close > last["EMA20"] and close > last["Open"]),
        "pullback_short": bool(downtrend and last["High"] >= last["EMA20"] * 0.99
                               and close < last["EMA20"] and close < last["Open"]),
        "pivots": pivots,
        "high_52w": d["High"].tail(250).max(),
        "low_52w": d["Low"].tail(250).min(),
    }

    nifty_close = nifty["Close"] if nifty is not None and not nifty.empty else None
    score, breakdown, warnings = _score_stock(d, w, nifty_close, regime, signals)

    bias = LONG if score >= min_score else SHORT if score <= -min_score else NEUTRAL
    setup = TradeSetup(
        symbol=symbol,
        close=round(close, 2),
        change_pct=float((close / prev["Close"] - 1) * 100),
        score=score,
        bias=bias,
        score_breakdown=breakdown,
        warnings=warnings,
    )

    # --- Levels -----------------------------------------------------------
    supports, resistances = support_resistance(d, close)
    fib = fib_retracement(d)
    pivot_list = list(pivots.as_dict().values())
    fib_list = list(fib.get("levels", {}).values())
    swing_list = [p for p, _ in supports + resistances]
    candidates = pivot_list + fib_list + swing_list + [signals["high_52w"], signals["low_52w"]]

    setup.levels = {
        "supports": supports,
        "resistances": resistances,
        "pivots": pivots.as_dict(),
        "fib": fib,
    }
    setup.indicators = {
        "RSI": round(_safe(last["RSI"]), 1),
        "ADX": round(_safe(last["ADX"]), 1),
        "ATR": round(_safe(last["ATR"]), 2),
        "EMA20": round(_safe(last["EMA20"]), 2),
        "EMA50": round(_safe(last["EMA50"]), 2),
        "SMA200": round(_safe(last["SMA200"]), 2),
        "VolRatio": None if math.isnan(vol_ratio) else round(vol_ratio, 2),
        "date": d.index[-1].date(),
    }

    # --- Plan -------------------------------------------------------------
    if bias != NEUTRAL:
        _build_plan(setup, d, candidates, capital, risk_pct, signals)
        setup.instrument = instrument_for(bias, score, _safe(last["ADX"], 0))
        setup.option_idea = option_idea(symbol, bias, close, today)
        if bias == LONG and regime.get("bullish") is False:
            setup.warnings.append("Nifty is in a downtrend - longs are against the market; reduce size.")
        if bias == SHORT and regime.get("bullish") is True:
            setup.warnings.append("Nifty is in an uptrend - shorts are against the market; reduce size.")

    setup.analysis = _build_analysis(setup, d, w, signals, pivots, supports, resistances, fib)
    return setup
