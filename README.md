# Nifty 50 Swing Screener

Scans all Nifty 50 stocks (all are F&O-eligible) on **daily + weekly** charts and
ranks the best **LONG** and **SHORT** positional setups. For each one you get:

- **Entry trigger** (Buy above / Sell below), **stop-loss**, **Target 1**, **Target 2**, R:R
- Setup type: Breakout, Breakdown, Pullback to 20 EMA, Trend continuation
- Instrument: Equity delivery, Futures, or an ITM/ATM Call/Put idea with expiry
- Position size for equity, plus max futures lots for your risk budget
- A full technical write-up: MAs, RSI, MACD, ADX, ATR, volume, weekly Fibonacci
  pivots, Fibonacci retracement, swing support/resistance, 52-week range,
  relative strength vs Nifty, and a score breakdown
- Candlestick charts (daily + weekly) with all levels drawn

## Setup (one time)

```bash
cd nifty_screener
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Mac / Linux
pip install -r requirements.txt
```

## Run

```bash
streamlit run app.py           # dashboard in your browser
python screener.py --capital 500000 --risk 1 --top 5 --csv picks.csv   # terminal version
python -m pytest -q            # tests (no internet needed)
```

Best time to run: **after 3:35 PM IST** (or before market open). The app only uses completed
candles unless you tick "Use today's live candle".

## Project layout

| File | What it does |
|---|---|
| `config.py` | Every setting (periods, thresholds, SL/target rules, stock list) |
| `data_fetcher.py` | Downloads data (only file that uses the internet; swap here for Dhan/Kite API) |
| `indicators.py` | EMA, SMA, RSI, ATR, MACD, ADX in plain pandas |
| `levels.py` | Fibonacci pivots, swing support/resistance, Fibonacci retracement |
| `strategy.py` | Scoring, trade plan, instrument choice, written analysis |
| `screener.py` | Runs all 50 stocks, ranks them, command-line output |
| `app.py` | Streamlit dashboard |

## How the score works (-100 to +100)

| Component | Max points |
|---|---|
| Daily trend: price vs 20/50 EMA and 200 SMA, 20 EMA slope | ±25 |
| Weekly trend: weekly close vs 10/20 EMA | ±15 |
| Momentum: RSI zone + MACD histogram | ±15 |
| Price action: 20-day breakout/breakdown (volume-confirmed = full points), 20 EMA pullback, close position | ±23 |
| Weekly Fibonacci pivot position (P, R1, S1) | ±10 |
| Relative strength vs Nifty (20 days) | ±10 |
| Nifty market trend | ±5 |
| ADX < 18 (sideways) | score x 0.7 |

Score ≥ +40 → LONG, ≤ -40 → SHORT (changeable in the sidebar).
Futures are suggested only when |score| ≥ 60 **and** ADX ≥ 20.

## Trade-plan rules

- **Entry**: above today's high (long) / below today's low (short) — next session confirmation.
- **Stop-loss**: beyond the 3-day swing low/high + 0.2 ATR, kept between 0.8 and 2 ATR from entry.
- **Target 1**: first real level (pivot / swing / Fib / 52-week) 1.5R–3R away, else 1.5R.
- **Target 2**: next level 2.5R–5R away, else 3R. Book ~50% at T1, trail the rest to cost.

## Important notes

- Yahoo data can be delayed or occasionally missing; the app skips stocks with gaps.
- **Lot sizes and strike intervals change** — enter the current lot size in the app and verify strikes on the option chain.
- Option exits are based on the **stock's** SL/targets, since option premiums are not downloaded.
- Update `FALLBACK_NIFTY50` in `config.py` after each March/September rebalance
  (the app tries to download the live list from NSE first).
- Educational tool, not investment advice.
