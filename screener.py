"""
screener.py
-----------
Runs the analysis on every Nifty 50 stock and ranks the results.

Command line use:
    python screener.py
    python screener.py --capital 500000 --risk 1 --min-score 45 --top 10 --csv picks.csv
"""

from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd

import config
from data_fetcher import DataFetchError, load_market_data
from strategy import LONG, SHORT, TradeSetup, analyse_stock, market_regime

logger = logging.getLogger(__name__)


def scan(
    stock_data: dict[str, pd.DataFrame],
    nifty: pd.DataFrame | None,
    capital: float,
    risk_pct: float,
    min_score: int,
    progress=None,
) -> tuple[list[TradeSetup], dict[str, str]]:
    """
    Analyse every stock. Returns (setups sorted by |score|, errors by symbol).
    `progress` is an optional callback: progress(done, total, symbol).
    """
    if capital <= 0:
        raise ValueError("Capital must be greater than zero.")
    if not 0 < risk_pct <= 10:
        raise ValueError("Risk per trade must be between 0 and 10 %.")

    regime = market_regime(nifty)
    setups: list[TradeSetup] = []
    errors: dict[str, str] = {}
    total = len(stock_data)

    for i, (symbol, frame) in enumerate(stock_data.items(), start=1):
        try:
            setups.append(analyse_stock(symbol, frame, nifty, regime, capital, risk_pct, min_score))
        except (ValueError, KeyError, IndexError, ZeroDivisionError) as exc:
            errors[symbol] = str(exc)
            logger.warning("Skipped %s: %s", symbol, exc)
        if progress:
            progress(i, total, symbol)

    setups.sort(key=lambda s: abs(s.score), reverse=True)
    return setups, errors


def to_dataframe(setups: list[TradeSetup]) -> pd.DataFrame:
    return pd.DataFrame([s.to_row() for s in setups])


def top_picks(setups: list[TradeSetup], bias: str, n: int) -> list[TradeSetup]:
    """Best n setups of one bias that have a complete trade plan."""
    picks = [s for s in setups if s.bias == bias and s.entry is not None]
    return picks[:n]


def _print_table(title: str, picks: list[TradeSetup]):
    print(f"\n=== {title} ===")
    if not picks:
        print("  No qualifying stocks.")
        return
    cols = ["Symbol", "Score", "Setup", "Close", "Trigger", "Entry", "Stop Loss",
            "Target 1", "Target 2", "R:R T2", "Equity Qty", "Instrument"]
    print(to_dataframe(picks)[cols].to_string(index=False))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Nifty 50 positional screener")
    parser.add_argument("--capital", type=float, default=100000, help="Trading capital in Rs")
    parser.add_argument("--risk", type=float, default=1.0, help="Risk per trade in %% of capital")
    parser.add_argument("--min-score", type=int, default=config.DEFAULT_MIN_SCORE)
    parser.add_argument("--top", type=int, default=5, help="Picks to show per side")
    parser.add_argument("--csv", type=str, default="", help="Save full results to this CSV file")
    parser.add_argument("--live", action="store_true", help="Include today's incomplete candle")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    try:
        print("Downloading Nifty 50 data ...")
        _, stock_data, nifty, missing = load_market_data(include_live_candle=args.live)
        setups, errors = scan(stock_data, nifty, args.capital, args.risk, args.min_score)
    except (DataFetchError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    regime = market_regime(nifty)
    if regime["available"]:
        trend = {True: "UPTREND", False: "DOWNTREND", None: "SIDEWAYS"}[regime["bullish"]]
        print(f"Nifty 50: {regime['close']:,.2f} ({regime['change_pct']:+.2f}%) - {trend}  [data up to {regime['date']}]")

    _print_table("TOP LONG SETUPS", top_picks(setups, LONG, args.top))
    _print_table("TOP SHORT SETUPS", top_picks(setups, SHORT, args.top))

    if missing or errors:
        print(f"\nSkipped: {', '.join(missing + list(errors))}")
    if args.csv:
        to_dataframe(setups).to_csv(args.csv, index=False)
        print(f"\nFull results saved to {args.csv}")
    print("\nEducational tool, not investment advice. Always confirm on your own charts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
