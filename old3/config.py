# config.py

# ============================================================
# TIME
# ============================================================

TIMEZONE = "America/New_York"


# ============================================================
# TIMEFRAMES
# ============================================================

TIMEFRAMES = {
    "5m": 5,
    "30m": 30,
    "day": "day",
}


# ============================================================
# INDICATORS
# ============================================================

EMA_PERIODS = (
    3,
    5,
    9,
    14,
    21,
    30,
    50,
    100,
    200,
)

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

GREEN_CANDLE_WINDOW = 200
RED_CANDLE_WINDOW = 200


# ============================================================
# STRATEGY
# ============================================================

STRATEGIES = (
    "ema_cross",
)


# ============================================================
# METHODS
# ============================================================

STOP_LOSS_MULTIPLIERS = (
    1,
    2,
)

RISK_REWARD_RATIOS = (
    1,
    1.5,
    2,
    3,
    5,
)

MAX_METHODS_TO_TRADE = 20

ENTRY_GREEN_RANGE_MULTIPLIER = 15
ENTRY_RED_RANGE_MULTIPLIER = 15


# ============================================================
# MARKET DATA
# ============================================================

TICK_MINUTES = 5
TICK_DELAY_SECONDS = 10

# Only completed bars are used for indicator/strategy calculations.
# The most recent bar is always excluded.
BAR_DELAY = 1


# ============================================================
# TRADING
# ============================================================

FRACTIONAL_SHARES = False

MARKET_HOURS_ONLY = True

# Capital is manually set at the beginning of each trading day.
DAILY_CAPITAL = 10_000


# ============================================================
# STORAGE
# ============================================================

R2_BUCKET = "stocks-data"

EQUITY_PATH = "equity"
CONTRIBUTION_PATH = "contributions"
ACTIVE_TRADES_PATH = "active_trades"


# ============================================================
# ALPACA
# ============================================================

ALPACA_PAPER_TRADING = True

ALPACA_ENTRY_ORDER_TYPE = "market"

ALPACA_ORDER_TIME_IN_FORCE = "gtc"