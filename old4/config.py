"""
config.py

Central configuration module for the trading architecture.
Contains all fixed parameters, constants, paths, and environment settings.
"""

import os
from zoneinfo import ZoneInfo

# ========= Start: 1. Timezone & Runtime Settings =============
TIMEZONE = ZoneInfo("America/New_York")
POLL_INTERVAL_SECONDS = 60
STARTING_EQUITY = 100.0
MAX_TRADE_METHODS = 20
# ====== End: 1. Timezone & Runtime Settings =======


# ========= Start: 2. Alpaca API Configuration =============
ALPACA_API_KEY = "PKA4A6THLEKI6QD2MQPOAO25J3"
ALPACA_SECRET_KEY = "4nj9w53vMrNKJGZsHqN7Siqy34z2Gis9TffWi2beszNU"
ALPACA_BASE_URL = "https://paper-api.alpaca.markets"
ALPACA_DATA_URL = "https://data.alpaca.markets"
# ====== End: 2. Alpaca API Configuration =======


# ========= Start: 3. Cloud Storage (R2) Settings =============
R2_ENDPOINT_URL = "https://98f8e959e677f16bddcf44f609fec6a0.r2.cloudflarestorage.com"
R2_ACCESS_KEY_ID = "00e18b0c16ecb3395cd6f7c8e0eb3554"
R2_SECRET_ACCESS_KEY = "33799355abaedc234309dbfbc80a2a66c3bfd856f0dcaecf0031e1fbcbcd84a0"
R2_BUCKET_NAME = "stocks-data"

R2_PATHS = {
    "raw_data": "{symbol}.parquet",
    "equity": "equity/{symbol}.parquet",
    "contributions": "contributions/contributions.parquet",
}
# ====== End: 3. Cloud Storage (R2) Settings =======


# ========= Start: 4. Market Data & Timeframe Settings =============
TIMEFRAMES = ("5m", "30m", "1d")
DERIVED_TIMEFRAMES = ("1d",)

HISTORICAL_LOOKBACK_BARS = 500
# ====== End: 4. Market Data & Timeframe Settings =======


# ========= Start: 5. Indicator Calculation Settings =============
EMA_PERIODS = (3, 5, 9, 14, 21, 30, 50, 100, 200)

EMA_PAIRS = (
    (3, 5),
    (5, 9),
    (9, 14),
    (14, 21),
    (21, 30),
    (30, 50),
    (50, 100),
    (100, 200),
)

ROC_PERIOD = 30
CANDLE_AVERAGE_WINDOW = 200
# ====== End: 5. Indicator Calculation Settings =======


# ========= Start: 6. Strategy & Execution Rules =============
STRATEGIES = ("ema_cross",)
SL_MULTIPLIERS = (1, 2)
RISK_REWARD_VALUES = (1.0, 1.5, 2.0, 3.0, 5.0)

ENTRY_RANGE_MULTIPLIER = 15
# ====== End: 6. Strategy & Execution Rules =======


# ========= Start: 7. Universe Settings =============
SYMBOLS = (
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "TSLA",
)
STOCK_UNIVERSE = SYMBOLS
# ====== End: 7. Universe Settings =======