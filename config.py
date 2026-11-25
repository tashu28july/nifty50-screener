"""
config.py
---------
All tunable settings live here. Change values in this file instead of
editing the logic in the other modules.
"""

from datetime import time
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Market / data settings
# ---------------------------------------------------------------------------
IST = ZoneInfo("Asia/Kolkata")
MARKET_CLOSE = time(15, 35)          # small buffer after the 15:30 close

# Official NSE constituent list (downloaded at run time when reachable)
NSE_NIFTY50_CSV_URL = "https://archives.nseindia.com/content/indices/ind_nifty50list.csv"

# Fallback list, used only if the NSE download fails.
# Reflects the 30-Sep-2026 rebalance (BSE replaced WIPRO). Update after
# every semi-annual rebalance (end of March and end of September).
FALLBACK_NIFTY50 = (
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL",
    "BSE", "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT",
    "ETERNAL", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE",
    "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDIGO", "INFY",
    "ITC", "JIOFIN", "JSWSTEEL", "KOTAKBANK", "LT",
    "M&M", "MARUTI", "MAXHEALTH", "NESTLEIND", "NTPC",
    "ONGC", "POWERGRID", "RELIANCE", "SBILIFE", "SBIN",
    "SHRIRAMFIN", "SUNPHARMA", "TATACONSUM", "TMPV", "TATASTEEL",
    "TCS", "TECHM", "TITAN", "TRENT", "ULTRACEMCO",
)

NIFTY_INDEX_TICKER = "^NSEI"
YAHOO_SUFFIX = ".NS"
HISTORY_PERIOD = "2y"                # enough bars for the 200-day average
MIN_BARS = 220                       # skip stocks with less history
DOWNLOAD_RETRIES = 2

# ---------------------------------------------------------------------------
# Indicator periods
# ---------------------------------------------------------------------------
EMA_FAST = 20
EMA_MID = 50
SMA_SLOW = 200
RSI_PERIOD = 14
ATR_PERIOD = 14
ADX_PERIOD = 14
VOLUME_AVG_PERIOD = 20
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9

WEEKLY_EMA_FAST = 10
WEEKLY_EMA_SLOW = 20

# ---------------------------------------------------------------------------
# Price-action settings
# ---------------------------------------------------------------------------
BREAKOUT_LOOKBACK = 20               # bars used for breakout / breakdown
VOLUME_SURGE_MULT = 1.5              # volume >= 1.5x average = confirmation
SWING_WINDOW = 5                     # bars on each side for a swing point
SR_LOOKBACK = 120                    # bars scanned for support/resistance
SR_CLUSTER_PCT = 1.0                 # merge levels within 1 %
FIB_SWING_LOOKBACK = 60              # bars used for Fibonacci retracement
RS_LOOKBACK = 20                     # relative strength vs Nifty

# ---------------------------------------------------------------------------
# Trade-plan settings (all in multiples of ATR or of risk "R")
# ---------------------------------------------------------------------------
SL_ATR_MAX = 2.0                     # stop never wider than 2 x ATR
SL_ATR_MIN = 0.8                     # stop never tighter than 0.8 x ATR
SL_ATR_BUFFER = 0.2                  # buffer below swing low / above swing high
T1_MIN_R = 1.5                       # target 1 at least 1.5 R
T1_MAX_R = 3.0
T2_MIN_R = 2.5                       # target 2 at least 2.5 R
T2_MAX_R = 5.0
T2_DEFAULT_R = 3.0
TICK_SIZE = 0.05

# ---------------------------------------------------------------------------
# Scoring thresholds
# ---------------------------------------------------------------------------
DEFAULT_MIN_SCORE = 40               # |score| needed for a LONG/SHORT call
FUTURES_MIN_SCORE = 60               # |score| needed to suggest futures
FUTURES_MIN_ADX = 20
CHOPPY_ADX = 18                      # below this the score is reduced
CHOPPY_PENALTY = 0.7                 # score multiplier in choppy markets

# ---------------------------------------------------------------------------
# Options settings
# ---------------------------------------------------------------------------
# NSE stock options are monthly and expire on the last Tuesday of the month
# (holidays move it to the previous trading day). Verify with your broker.
STOCK_EXPIRY_WEEKDAY = 1             # Monday=0, Tuesday=1
ROLL_TO_NEXT_MONTH_DAYS = 10         # fewer days left -> use next month
