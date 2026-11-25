"""
data_fetcher.py
---------------
Downloads the Nifty 50 constituent list and daily price history.
Only this file talks to the internet, so you can later swap yfinance for
the Dhan / Kite API without touching the analysis code.
"""

from __future__ import annotations

import io
import logging
import time as _time
from datetime import datetime

import pandas as pd
import requests
import yfinance as yf

import config

logger = logging.getLogger(__name__)

PRICE_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


class DataFetchError(Exception):
    """Raised when market data cannot be downloaded."""


def get_nifty50_symbols() -> list[str]:
    """Return the current Nifty 50 symbols (NSE download, else fallback list)."""
    try:
        response = requests.get(
            config.NSE_NIFTY50_CSV_URL,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        response.raise_for_status()
        table = pd.read_csv(io.StringIO(response.text))
        symbols = table["Symbol"].dropna().astype(str).str.strip().tolist()
        if len(symbols) >= 45:            # sanity check on the download
            return symbols
        logger.warning("NSE list looked incomplete (%d rows); using fallback.", len(symbols))
    except (requests.RequestException, KeyError, pd.errors.ParserError) as exc:
        logger.warning("Could not download Nifty 50 list (%s); using fallback.", exc)
    return list(config.FALLBACK_NIFTY50)


def to_yahoo_ticker(symbol: str) -> str:
    """NSE symbol -> Yahoo Finance ticker (e.g. SBIN -> SBIN.NS)."""
    return f"{symbol}{config.YAHOO_SUFFIX}"


def drop_incomplete_bar(df: pd.DataFrame, now: datetime | None = None) -> pd.DataFrame:
    """Remove today's bar if the market has not closed yet."""
    if df.empty:
        return df
    now = now or datetime.now(config.IST)
    last_date = df.index[-1].date()
    if last_date == now.date() and now.time() < config.MARKET_CLOSE:
        return df.iloc[:-1]
    return df


def clean_price_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Keep OHLCV columns, remove bad rows, make the index a plain date index."""
    if df is None or df.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS)
    missing = [c for c in PRICE_COLUMNS if c not in df.columns]
    if missing:
        logger.warning("Missing columns %s; skipping frame.", missing)
        return pd.DataFrame(columns=PRICE_COLUMNS)

    out = df[PRICE_COLUMNS].copy()
    out = out.dropna(subset=["Open", "High", "Low", "Close"])
    out["Volume"] = out["Volume"].fillna(0)
    out = out[(out["High"] >= out["Low"]) & (out["Close"] > 0)]

    out.index = pd.to_datetime(out.index)
    if out.index.tz is not None:
        out.index = out.index.tz_localize(None)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


def _download(tickers: list[str], period: str) -> pd.DataFrame:
    """yfinance download with a simple retry (Yahoo sometimes rate-limits)."""
    last_error: Exception | None = None
    for attempt in range(1, config.DOWNLOAD_RETRIES + 1):
        try:
            raw = yf.download(
                tickers=tickers,
                period=period,
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                progress=False,
                threads=True,
            )
            if raw is not None and not raw.empty:
                return raw
            last_error = DataFetchError("Empty response from Yahoo Finance")
        except Exception as exc:          # yfinance raises many error types
            last_error = exc
        logger.warning("Download attempt %d failed: %s", attempt, last_error)
        _time.sleep(2 * attempt)
    raise DataFetchError(f"Could not download price data: {last_error}")


def fetch_daily_history(
    tickers: list[str],
    period: str = config.HISTORY_PERIOD,
    include_live_candle: bool = False,
) -> dict[str, pd.DataFrame]:
    """Download daily OHLCV for many tickers. Returns {ticker: DataFrame}."""
    if not tickers:
        return {}
    raw = _download(tickers, period)
    result: dict[str, pd.DataFrame] = {}

    for ticker in tickers:
        if isinstance(raw.columns, pd.MultiIndex):
            if ticker not in raw.columns.get_level_values(0):
                logger.warning("No data for %s", ticker)
                continue
            frame = raw[ticker]
        else:
            frame = raw
        frame = clean_price_frame(frame)
        if not include_live_candle:
            frame = drop_incomplete_bar(frame)
        if not frame.empty:
            result[ticker] = frame
    return result


def to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    """Convert daily candles to weekly candles (weeks end on Friday)."""
    if daily.empty:
        return daily
    weekly = daily.resample("W-FRI").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    )
    return weekly.dropna(subset=["Close"])


def load_market_data(include_live_candle: bool = False):
    """
    One call that gets everything the screener needs.

    Returns
    -------
    symbols : list[str]                 Nifty 50 symbols
    stock_data : dict[str, DataFrame]   keyed by NSE symbol
    nifty : DataFrame | None            Nifty 50 index daily data
    missing : list[str]                 symbols with no data
    """
    symbols = get_nifty50_symbols()
    tickers = [to_yahoo_ticker(s) for s in symbols] + [config.NIFTY_INDEX_TICKER]
    history = fetch_daily_history(tickers, include_live_candle=include_live_candle)

    stock_data = {}
    missing = []
    for symbol in symbols:
        frame = history.get(to_yahoo_ticker(symbol))
        if frame is None or frame.empty:
            missing.append(symbol)
        else:
            stock_data[symbol] = frame

    nifty = history.get(config.NIFTY_INDEX_TICKER)
    return symbols, stock_data, nifty, missing
