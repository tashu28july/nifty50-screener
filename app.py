"""
app.py
------
Streamlit dashboard for the Nifty 50 screener.

Run with:
    streamlit run app.py
"""

from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import config
from data_fetcher import DataFetchError, load_market_data, to_weekly
from indicators import add_daily_indicators, add_weekly_indicators
from screener import scan, to_dataframe, top_picks
from strategy import LONG, NEUTRAL, SHORT, TradeSetup, market_regime

st.set_page_config(page_title="Nifty 50 Swing Screener", page_icon="📈", layout="wide")


# ---------------------------------------------------------------------------
# Cached data loading (refreshes every 15 minutes or on button click)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=900, show_spinner=False)
def cached_market_data(include_live: bool):
    return load_market_data(include_live_candle=include_live)


@st.cache_data(ttl=900, show_spinner=False)
def cached_scan(include_live: bool, capital: float, risk_pct: float, min_score: int):
    _, stock_data, nifty, missing = cached_market_data(include_live)
    setups, errors = scan(stock_data, nifty, capital, risk_pct, min_score)
    return setups, errors, missing


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
def _add_level(fig, price, label, color, dash="dash"):
    if price is None or (isinstance(price, float) and math.isnan(price)):
        return
    fig.add_hline(y=price, line_color=color, line_dash=dash, line_width=1.2,
                  annotation_text=f"{label} {price:,.2f}", annotation_position="right",
                  annotation_font_color=color, row=1, col=1)


def price_chart(df: pd.DataFrame, setup: TradeSetup, weekly: bool) -> go.Figure:
    bars = 104 if weekly else 150
    data = df.tail(bars)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.78, 0.22], vertical_spacing=0.03)

    fig.add_trace(go.Candlestick(x=data.index, open=data["Open"], high=data["High"], low=data["Low"],
                                 close=data["Close"], name="Price",
                                 increasing_line_color="#1a9850", decreasing_line_color="#d73027"), row=1, col=1)

    ma_cols = [("WEMA_FAST", "W 10 EMA", "#f39c12"), ("WEMA_SLOW", "W 20 EMA", "#2980b9")] if weekly else \
              [("EMA20", "20 EMA", "#f39c12"), ("EMA50", "50 EMA", "#2980b9"), ("SMA200", "200 SMA", "#8e44ad")]
    for col, name, color in ma_cols:
        fig.add_trace(go.Scatter(x=data.index, y=data[col], name=name, line=dict(color=color, width=1.4)), row=1, col=1)

    vol_colors = ["#1a9850" if c >= o else "#d73027" for c, o in zip(data["Close"], data["Open"])]
    fig.add_trace(go.Bar(x=data.index, y=data["Volume"], marker_color=vol_colors, name="Volume", showlegend=False),
                  row=2, col=1)

    if not weekly:
        for price, touches in setup.levels.get("supports", [])[:3]:
            _add_level(fig, price, f"S ({touches}x)", "rgba(26,152,80,0.55)", "dot")
        for price, touches in setup.levels.get("resistances", [])[:3]:
            _add_level(fig, price, f"R ({touches}x)", "rgba(215,48,39,0.55)", "dot")
    if setup.bias != NEUTRAL:
        _add_level(fig, setup.entry, "Entry", "#2c3e50", "solid")
        _add_level(fig, setup.stop_loss, "SL", "#c0392b", "solid")
        _add_level(fig, setup.target1, "T1", "#27ae60", "solid")
        _add_level(fig, setup.target2, "T2", "#16a085", "solid")

    fig.update_layout(height=620, margin=dict(l=10, r=110, t=30, b=10), xaxis_rangeslider_visible=False,
                      legend=dict(orientation="h", y=1.04, x=0), hovermode="x unified")
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])] if not weekly else [])
    return fig


# ---------------------------------------------------------------------------
# UI pieces
# ---------------------------------------------------------------------------
TABLE_COLS = ["Symbol", "Score", "Setup", "Close", "Chg %", "Trigger", "Entry", "Stop Loss",
              "Target 1", "Target 2", "R:R T1", "R:R T2", "Equity Qty", "Instrument", "RSI", "ADX", "Vol x Avg"]


def show_regime(nifty):
    regime = market_regime(nifty)
    if not regime["available"]:
        st.warning("Nifty index data unavailable - market-trend filter is off.")
        return
    trend = {True: "🟢 Uptrend", False: "🔴 Downtrend", None: "🟡 Sideways"}[regime["bullish"]]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Nifty 50", f"{regime['close']:,.2f}", f"{regime['change_pct']:+.2f}%")
    c2.metric("Market trend", trend)
    c3.metric("20 EMA / 50 EMA", f"{regime['ema20']:,.0f} / {regime['ema50']:,.0f}")
    c4.metric("Nifty RSI", f"{regime['rsi']:.1f}")
    c5.metric("Data up to", str(regime["date"]))


def show_table(picks: list[TradeSetup], empty_msg: str):
    if not picks:
        st.info(empty_msg)
        return
    df = to_dataframe(picks)[TABLE_COLS]
    st.dataframe(df, hide_index=True, width="stretch",
                 column_config={"Score": st.column_config.ProgressColumn("Score", min_value=-100, max_value=100,
                                                                         format="%d")})


def show_detail(setup: TradeSetup, daily: pd.DataFrame):
    badge = {"LONG": "🟢 LONG", "SHORT": "🔴 SHORT", "NEUTRAL": "⚪ NEUTRAL"}[setup.bias]
    st.subheader(f"{setup.symbol}  -  {badge}  (score {setup.score})")

    if setup.bias != NEUTRAL:
        c = st.columns(6)
        c[0].metric(setup.entry_type, f"₹{setup.entry:,.2f}")
        c[1].metric("Stop Loss", f"₹{setup.stop_loss:,.2f}", f"-{setup.risk_per_share:,.2f}/share", delta_color="off")
        c[2].metric("Target 1", f"₹{setup.target1:,.2f}", f"R:R {setup.rr_t1}")
        c[3].metric("Target 2", f"₹{setup.target2:,.2f}", f"R:R {setup.rr_t2}")
        c[4].metric("Setup", setup.setup_type)
        c[5].metric("Equity qty", setup.equity_qty if setup.bias == LONG else "n/a (no overnight short)")

        st.markdown(f"**Suggested instrument:** {setup.instrument}")
        st.markdown(f"**Option idea:** {setup.option_idea}")

        lot = st.number_input(f"{setup.symbol} F&O lot size (check NSE/broker - lot sizes change)",
                              min_value=0, value=0, step=1, key=f"lot_{setup.symbol}")
        if lot > 0 and setup.risk_per_share:
            risk_per_lot = setup.risk_per_share * lot
            budget = st.session_state.get("capital", 0) * st.session_state.get("risk_pct", 0) / 100
            max_lots = int(budget // risk_per_lot) if risk_per_lot > 0 else 0
            st.markdown(f"Risk per futures lot: **₹{risk_per_lot:,.0f}** -> max **{max_lots} lot(s)** "
                        f"for your ₹{budget:,.0f} risk budget.")
            if max_lots == 0:
                st.warning("One lot risks more than your per-trade budget. Use an option or skip this trade.")

    for warning in setup.warnings:
        st.warning(warning)

    tab_d, tab_w = st.tabs(["Daily chart", "Weekly chart"])
    with tab_d:
        st.plotly_chart(price_chart(add_daily_indicators(daily), setup, weekly=False), width="stretch")
    with tab_w:
        weekly = add_weekly_indicators(to_weekly(daily))
        st.plotly_chart(price_chart(weekly, setup, weekly=True), width="stretch")

    left, right = st.columns([3, 2])
    with left:
        st.markdown("#### Technical analysis")
        for line in setup.analysis:
            st.markdown(f"- {line}")
    with right:
        st.markdown("#### Score breakdown")
        st.code("\n".join(setup.score_breakdown) + f"\n{'-' * 30}\nTotal: {setup.score}", language=None)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
def main():
    st.title("📈 Nifty 50 Swing Screener")
    st.caption("Positional setups for Equity, Futures and Options from daily + weekly price action, "
               "moving averages, Fibonacci pivots, support/resistance and breakouts.")

    with st.sidebar:
        st.header("Settings")
        capital = st.number_input("Trading capital (₹)", min_value=10000, value=500000, step=10000, key="capital")
        risk_pct = st.slider("Risk per trade (% of capital)", 0.25, 5.0, 1.0, 0.25, key="risk_pct")
        min_score = st.slider("Minimum score for a signal", 20, 80, config.DEFAULT_MIN_SCORE, 5)
        top_n = st.slider("Picks to show per side", 3, 25, 10)
        include_live = st.checkbox("Use today's live candle (during market hours)", value=False,
                                   help="Off = analyse only completed daily candles (recommended).")
        if st.button("🔄 Refresh data", width="stretch"):
            st.cache_data.clear()
        st.divider()
        st.caption("Data: Yahoo Finance (may be ~15 min delayed). Educational tool - not investment advice.")

    try:
        with st.spinner("Downloading Nifty 50 data and scanning ..."):
            _, stock_data, nifty, _ = cached_market_data(include_live)
            setups, errors, missing = cached_scan(include_live, float(capital), float(risk_pct), int(min_score))
    except DataFetchError as exc:
        st.error(f"Could not download market data: {exc}. Check your internet connection and click Refresh.")
        st.stop()
    except ValueError as exc:
        st.error(str(exc))
        st.stop()

    if not setups:
        st.error("No stocks could be analysed. Try Refresh in a minute.")
        st.stop()

    show_regime(nifty)

    longs = top_picks(setups, LONG, top_n)
    shorts = top_picks(setups, SHORT, top_n)
    neutral_count = sum(1 for s in setups if s.bias == NEUTRAL)
    st.markdown(f"**{len(setups)} stocks scanned** - {len(longs)} long, {len(shorts)} short shown, "
                f"{neutral_count} neutral.")

    tab_long, tab_short, tab_all = st.tabs(["🟢 Top long setups", "🔴 Top short setups", "📋 All stocks"])
    with tab_long:
        show_table(longs, "No long setups above the minimum score right now.")
    with tab_short:
        show_table(shorts, "No short setups above the minimum score right now.")
    with tab_all:
        all_df = to_dataframe(setups)
        st.dataframe(all_df[TABLE_COLS[:6] + ["RSI", "ADX", "Vol x Avg"]], hide_index=True,
                     width="stretch")
        st.download_button("⬇️ Download full results (CSV)", all_df.to_csv(index=False).encode("utf-8"),
                           file_name="nifty50_scan.csv", mime="text/csv")

    if missing or errors:
        with st.expander(f"Skipped {len(missing) + len(errors)} stock(s)"):
            for sym in missing:
                st.write(f"{sym}: no data downloaded")
            for sym, msg in errors.items():
                st.write(f"{sym}: {msg}")

    st.divider()
    st.markdown("### 🔍 Stock deep-dive")
    by_symbol = {s.symbol: s for s in setups}
    default = (longs or shorts or setups)[0].symbol
    options = sorted(by_symbol)
    choice = st.selectbox("Choose a stock", options, index=options.index(default))
    show_detail(by_symbol[choice], stock_data[choice])

    st.divider()
    st.caption("How to use: wait for price to trade beyond the trigger (Buy above / Sell below) in the next "
               "session, place the SL immediately, book part at T1 and trail the rest. Skip trades with an "
               "earnings result or big event inside the holding period. This is a rules-based screen, not a "
               "recommendation; you are responsible for your own trades.")


if __name__ == "__main__":
    main()
