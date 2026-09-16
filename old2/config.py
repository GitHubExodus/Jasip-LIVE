# config.py

# ============================================================
# TIMEFRAMES
# ============================================================

TIMEFRAMES = {
    "5m": {
        "minutes": 5,
        "source": None,
    },
    "30m": {
        "minutes": 30,
        "source": "5m",
    },
    "day": {
        "minutes": 1440,
        "source": "30m",
    },
    "week": {
        "minutes": 10080,
        "source": "day",
    },
}


# ============================================================
# INDICATORS
# ============================================================

EMA_PERIODS = [
    3,
    5,
    9,
    14,
    21,
    30,
    50,
    100,
    200,
]

EMA_PAIRS = [
    (3, 5),
    (5, 9),
    (9, 14),
    (14, 21),
    (21, 30),
    (30, 50),
    (50, 100),
    (100, 200),
]

ROC_PERIOD = 30

CANDLE_AVERAGE_WINDOW = 200


# ============================================================
# STRATEGIES
# ============================================================

STRATEGIES = [
    "ema_crossover",
]


# ============================================================
# TRADE SETTINGS
# ============================================================

STOP_LOSS_MULTIPLIERS = [
    1,
    2,
]

RISK_REWARD_RATIOS = [
    1,
    1.5,
    2,
    3,
    5,
]


# ============================================================
# ENTRY FILTER
# ============================================================

ENTRY_RANGE_MULTIPLIER = 15


# ============================================================
# METHOD SELECTION
# ============================================================

MAX_TRADABLE_METHODS = 20


# ============================================================
# MARKET DATA
# ============================================================

BASE_TIMEFRAME = "5m"

MARKET_TIMEZONE = "America/New_York"

MARKET_DATA_START_DATE = "2020-01-01"


# ============================================================
# 5-MINUTE CANDLE TIMING
# ============================================================

# How long to wait after a 5-minute candle boundary before
# requesting the newly completed candle.
CANDLE_CONFIRMATION_DELAY_SECONDS = 10


# ============================================================
# CLOUD STORAGE
# ============================================================

R2_BUCKET = "stocks-data"

R2_PATHS = {
    "input": "input",
    "output": "output",
    "misc": "misc",
    "input_statistics": "input_statistics",
    "risk_reward": "riskreward",
    "equity_curves": "evaluate/equity_curves",
    "contributions": "evaluate/contributions",
}


# ============================================================
# ALPACA
# ============================================================

ALPACA_PAPER_TRADING = True

ALPACA_FEED = "iex"


# ============================================================
# SHARE CALCULATION
# ============================================================

ALLOW_FRACTIONAL_SHARES = False