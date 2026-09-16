import os



# ============================================================
# ALPACA
# ============================================================

ALPACA_API_KEY = "PKA4A6THLEKI6QD2MQPOAO25J3"
ALPACA_SECRET_KEY = "4nj9w53vMrNKJGZsHqN7Siqy34z2Gis9TffWi2beszNU"

# Paper trading
ALPACA_PAPER = True


# ============================================================
# R2
# ============================================================

R2_ENDPOINT_URL = "https://98f8e959e677f16bddcf44f609fec6a0.r2.cloudflarestorage.com"
R2_ACCESS_KEY_ID = "00e18b0c16ecb3395cd6f7c8e0eb3554"
R2_SECRET_ACCESS_KEY = "33799355abaedc234309dbfbc80a2a66c3bfd856f0dcaecf0031e1fbcbcd84a0"
R2_BUCKET_NAME = "stocks-data"

# ============================================================
# TOP METHODS
# ============================================================

TOP_METHODS_R2_KEY = (
    "global_equity/raw_equity_rankings.parquet"
)


# ============================================================
# EQUITY
# ============================================================

STARTING_EQUITY = 100.000


# ============================================================
# TIMEZONE
# ============================================================

NEW_YORK_TIMEZONE = (
    "America/New_York"
)


# ============================================================
# EMA STRATEGIES
# ============================================================

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


# ============================================================
# DATA
# ============================================================

SUPPORTED_TIMEFRAMES = (
    "1m",
    "5m",
    "30m",
    "1h",
    "1d",
    "1w",
)


# ============================================================
# STARTUP HISTORY
#
# Number of bars kept in memory after downloading.
#
# We download enough data for the requested EMA periods,
# then retain this many recent bars.
# ============================================================

HISTORICAL_BARS = 1000


# ============================================================
# ORDER SETTINGS
# ============================================================

ORDER_QUANTITY = 1


# ============================================================
# TRADING
# ============================================================

ALLOW_LONG = True


# ============================================================
# EXTENDED HOURS
# ============================================================

# NOTE:
#
# Alpaca requires extended-hours eligible orders to be
# limit orders. Our strategy uses market-entry bracket orders,
# therefore this remains False.
#
# Market-data history/stream still contains extended-hours
# bars.
#

EXTENDED_HOURS_ORDERS = False