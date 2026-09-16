import math
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.live import StockDataStream
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
from alpaca.trading.requests import (
    MarketOrderRequest,
    TakeProfitRequest,
    StopLossRequest,
)

import old.config as config
import old.strategies as strategies
import old.storage as storage


# ============================================================
# CONFIG
# ============================================================

NY = ZoneInfo("America/New_York")

STARTING_EQUITY = 100.000

TOP_METHODS_R2_KEY = "global_equity/raw_equity_rankings.parquet"

# Historical warmup.
#
# 200 is currently the largest EMA period used by the EMA
# strategies. More bars are downloaded so the EMA has enough
# warmup data.
HISTORICAL_BARS = 1000

# 4h is intentionally NOT included.
SUPPORTED_TIMEFRAMES = {
    "1m": TimeFrame(1, TimeFrameUnit.Minute),
    "5m": TimeFrame(5, TimeFrameUnit.Minute),
    "30m": TimeFrame(30, TimeFrameUnit.Minute),
    "1h": TimeFrame(1, TimeFrameUnit.Hour),
    "1d": TimeFrame(1, TimeFrameUnit.Day),
    "1w": TimeFrame(1, TimeFrameUnit.Week),
}

# EMA strategy definitions.
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

STOP_LOSSES = (
    0.005,
    0.010,
    0.020,
    0.030,
    0.050,
)

RISK_REWARDS = (
    1.0,
    1.5,
    2.0,
    3.0,
    5.0,
)


# ============================================================
# METHOD STATE
# ============================================================

@dataclass
class MethodState:
    method_id: str

    symbol: str
    timeframe: str
    strategy: str

    stop_loss_percent: float
    risk_reward: float

    fast_period: int
    slow_period: int

    equity: float = STARTING_EQUITY

    # Whether this method currently has a broker position/order.
    in_trade: bool = False

    # Historical EMA values immediately before the current
    # forming candle.
    previous_fast_ema: float = np.nan
    previous_slow_ema: float = np.nan

    # Current forming candle.
    candle_start: object = None
    candle_end: object = None

    candle_open: float = np.nan
    candle_high: float = np.nan
    candle_low: float = np.nan
    candle_close: float = np.nan

    # Fixed trigger for the CURRENT candle.
    entry_threshold: float = np.nan

    # Trade bookkeeping.
    entry_order_id: str | None = None
    entry_price: float | None = None

    parent_order_id: str | None = None
    take_profit_order_id: str | None = None
    stop_loss_order_id: str | None = None

    # Prevent duplicate submissions while an order is being
    # submitted/accepted by Alpaca.
    order_pending: bool = False


# ============================================================
# GLOBAL STATE
# ============================================================

METHODS: dict[str, MethodState] = {}

METHODS_BY_SYMBOL: dict[str, list[MethodState]] = {}

TIMEFRAME_METHODS: dict[str, list[MethodState]] = {}

LATEST_PRICES: dict[str, float] = {}

LATEST_PRICE_TIMESTAMPS: dict[str, datetime] = {}

LOCK = threading.RLock()


# ============================================================
# CLIENTS
# ============================================================

def get_env(name: str):
    value = getattr(config, name, None)

    if value is None:
        raise RuntimeError(
            f"Missing {name} in config.py"
        )

    return value


API_KEY = get_env("ALPACA_API_KEY")
SECRET_KEY = get_env("ALPACA_SECRET_KEY")

PAPER = getattr(config, "ALPACA_PAPER", True)

DATA_CLIENT = StockHistoricalDataClient(
    API_KEY,
    SECRET_KEY,
)

TRADING_CLIENT = TradingClient(
    API_KEY,
    SECRET_KEY,
    paper=PAPER,
)

STREAM = StockDataStream(
    API_KEY,
    SECRET_KEY,
)


# ============================================================
# HELPERS
# ============================================================

def ny_time(timestamp) -> datetime:
    """
    Convert any timestamp to America/New_York.

    Alpaca timestamps are the source of truth.
    """

    if isinstance(timestamp, pd.Timestamp):
        timestamp = timestamp.to_pydatetime()

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    return timestamp.astimezone(NY)


def timeframe_delta(timeframe: str) -> timedelta:
    if timeframe == "1m":
        return timedelta(minutes=1)

    if timeframe == "5m":
        return timedelta(minutes=5)

    if timeframe == "30m":
        return timedelta(minutes=30)

    if timeframe == "1h":
        return timedelta(hours=1)

    if timeframe == "1d":
        return timedelta(days=1)

    if timeframe == "1w":
        return timedelta(weeks=1)

    raise ValueError(f"Unsupported timeframe: {timeframe}")


def candle_bucket(timestamp: datetime, timeframe: str) -> datetime:
    """
    Determine which candle a timestamp belongs to.

    This is based entirely on the Alpaca timestamp after converting
    it to New York time.

    No computer/local timezone is used.
    """

    timestamp = ny_time(timestamp)

    if timeframe == "1m":
        return timestamp.replace(
            second=0,
            microsecond=0,
        )

    if timeframe == "5m":
        minute = (timestamp.minute // 5) * 5

        return timestamp.replace(
            minute=minute,
            second=0,
            microsecond=0,
        )

    if timeframe == "30m":
        minute = (timestamp.minute // 30) * 30

        return timestamp.replace(
            minute=minute,
            second=0,
            microsecond=0,
        )

    if timeframe == "1h":
        return timestamp.replace(
            minute=0,
            second=0,
            microsecond=0,
        )

    if timeframe == "1d":
        return timestamp.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

    if timeframe == "1w":
        # Monday is the beginning of the week.
        monday = timestamp - timedelta(days=timestamp.weekday())

        return monday.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

    raise ValueError(
        f"Unsupported timeframe: {timeframe}"
    )


def timeframe_end(timestamp: datetime, timeframe: str) -> datetime:
    return candle_bucket(timestamp, timeframe) + timeframe_delta(
        timeframe
    )


# ============================================================
# EMA
# ============================================================

def ema_alpha(period: int) -> float:
    return 2.0 / (period + 1.0)


def update_ema(previous_ema: float, price: float, period: int) -> float:
    alpha = ema_alpha(period)

    return (
        alpha * price
        + (1.0 - alpha) * previous_ema
    )


def calculate_entry_threshold(
    previous_fast_ema: float,
    previous_slow_ema: float,
    fast_period: int,
    slow_period: int,
) -> float:
    """
    Calculate the price at which the CURRENT candle produces
    a bullish EMA crossover.

    IMPORTANT:
    This only produces a valid fresh-cross threshold if the
    previous completed candle was NOT already bullish.

    If fast EMA is already above slow EMA, there is no fresh
    bullish crossover to trigger.
    """

    if not np.isfinite(previous_fast_ema):
        return np.nan

    if not np.isfinite(previous_slow_ema):
        return np.nan

    # Already bullish means there is no new bullish crossover
    # during this candle.
    if previous_fast_ema > previous_slow_ema:
        return np.nan

    fast_alpha = ema_alpha(fast_period)
    slow_alpha = ema_alpha(slow_period)

    denominator = fast_alpha - slow_alpha

    if denominator == 0:
        return np.nan

    threshold = (
        (
            (1.0 - slow_alpha) * previous_slow_ema
            -
            (1.0 - fast_alpha) * previous_fast_ema
        )
        / denominator
    )

    if not np.isfinite(threshold):
        return np.nan

    return float(threshold)


# ============================================================
# METHOD ID
# ============================================================

def make_method_id(
    symbol: str,
    timeframe: str,
    strategy: str,
    stop_loss_percent: float,
    risk_reward: float,
) -> str:

    sl_percent = stop_loss_percent

    if sl_percent <= 1:
        sl_percent = sl_percent * 100.0

    return (
        f"{symbol}_"
        f"{timeframe}_"
        f"{strategy}_"
        f"sl_{sl_percent:g}_"
        f"rr_{risk_reward:g}"
    )


# ============================================================
# TOP METHODS
# ============================================================

def download_top_methods() -> pd.DataFrame:
    """
    Download the global top-method ranking parquet from R2.

    This expects storage.py to expose a function capable of
    downloading a parquet object.

    If your existing storage.py already has the function used
    by the previous version of main.py, this function can be
    replaced with that exact call.
    """

    # Existing storage API may expose a dedicated helper.
    if hasattr(storage, "download_parquet"):
        return storage.download_parquet(
            TOP_METHODS_R2_KEY
        )

    if hasattr(storage, "load_parquet"):
        return storage.load_parquet(
            TOP_METHODS_R2_KEY
        )

    if hasattr(storage, "get_parquet"):
        return storage.get_parquet(
            TOP_METHODS_R2_KEY
        )

    raise RuntimeError(
        "storage.py must expose download_parquet(), "
        "load_parquet(), or get_parquet() for "
        f"{TOP_METHODS_R2_KEY}"
    )


def build_methods():
    ranking = download_top_methods()

    if ranking is None or ranking.empty:
        raise RuntimeError(
            "Top-method ranking parquet is empty."
        )

    required_columns = {
        "symbol",
        "timeframe",
        "strategy",
        "stop_loss_percent",
        "risk_reward",
    }

    missing = required_columns - set(
        ranking.columns
    )

    if missing:
        raise RuntimeError(
            f"Top-method parquet is missing columns: {missing}"
        )

    # Only top 100.
    ranking = ranking.head(100)

    for _, row in ranking.iterrows():

        symbol = str(row["symbol"]).upper()
        timeframe = str(row["timeframe"]).lower()
        strategy = str(row["strategy"])

        # Explicitly ignore 4h.
        if timeframe == "4h":
            continue

        if timeframe not in SUPPORTED_TIMEFRAMES:
            print(
                f"SKIP | unsupported timeframe | "
                f"{symbol} | {timeframe}"
            )
            continue

        if strategy.startswith("strategy_"):
            strategy_number = int(
                strategy.split("_")[1]
            )
        else:
            print(
                f"SKIP | unsupported strategy | "
                f"{strategy}"
            )
            continue

        if not (
            1 <= strategy_number <= len(EMA_PAIRS)
        ):
            print(
                f"SKIP | unsupported strategy | "
                f"{strategy}"
            )
            continue

        stop_loss = float(
            row["stop_loss_percent"]
        )

        risk_reward = float(
            row["risk_reward"]
        )

        # The parquet uses percentage values such as 5.
        # Convert to decimal for calculations.
        if stop_loss > 1:
            stop_loss_decimal = stop_loss / 100.0
        else:
            stop_loss_decimal = stop_loss

        fast_period, slow_period = EMA_PAIRS[
            strategy_number - 1
        ]

        method_id = make_method_id(
            symbol,
            timeframe,
            strategy,
            stop_loss_decimal,
            risk_reward,
        )

        method = MethodState(
            method_id=method_id,
            symbol=symbol,
            timeframe=timeframe,
            strategy=strategy,
            stop_loss_percent=stop_loss_decimal,
            risk_reward=risk_reward,
            fast_period=fast_period,
            slow_period=slow_period,
        )

        METHODS[method_id] = method

        METHODS_BY_SYMBOL.setdefault(
            symbol,
            [],
        ).append(method)

        TIMEFRAME_METHODS.setdefault(
            timeframe,
            [],
        ).append(method)

    if not METHODS:
        raise RuntimeError(
            "No valid methods were created."
        )

    print()
    print(
        f"Loaded {len(METHODS)} methods."
    )

    print(
        "Required timeframes:",
        ", ".join(
            TIMEFRAME_METHODS.keys()
        ),
    )

    print()

    for timeframe in SUPPORTED_TIMEFRAMES:
        count = len(
            TIMEFRAME_METHODS.get(
                timeframe,
                [],
            )
        )

        if count:
            print(
                f"  {timeframe}: {count} methods"
            )


# ============================================================
# HISTORICAL DATA
# ============================================================

def download_historical(
    symbol: str,
    timeframe: str,
) -> pd.DataFrame:

    tf = SUPPORTED_TIMEFRAMES[timeframe]

    end = datetime.now(timezone.utc)

    # Use a generous period for warmup.
    #
    # The request is still for the DIRECT Alpaca timeframe.
    # No 1m -> 5m -> 30m resampling occurs.
    if timeframe == "1m":
        start = end - timedelta(days=10)

    elif timeframe == "5m":
        start = end - timedelta(days=30)

    elif timeframe == "30m":
        start = end - timedelta(days=180)

    elif timeframe == "1h":
        start = end - timedelta(days=365)

    elif timeframe == "1d":
        start = end - timedelta(days=3650)

    elif timeframe == "1w":
        start = end - timedelta(days=3650)

    else:
        raise ValueError(
            f"Unsupported timeframe: {timeframe}"
        )

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=tf,
        start=start,
        end=end,
        limit=HISTORICAL_BARS,
        feed=DataFeed.IEX,
    )

    bars = DATA_CLIENT.get_stock_bars(
        request
    )

    df = bars.df

    if df is None or len(df) == 0:
        raise RuntimeError(
            f"No historical data for "
            f"{symbol} {timeframe}"
        )

    df = df.reset_index()

    if "symbol" in df.columns:
        df = df.drop(
            columns=["symbol"]
        )

    df["timestamp"] = pd.to_datetime(
        df["timestamp"],
        utc=True,
    ).dt.tz_convert(
        "America/New_York"
    )

    df = df.sort_values(
        "timestamp"
    ).reset_index(
        drop=True
    )

    return df


# ============================================================
# HISTORICAL EMA STATE
# ============================================================

def initialize_method_from_history(
    method: MethodState,
    df: pd.DataFrame,
):
    closes = np.asarray(
        df["close"],
        dtype=np.float64,
    )

    if len(closes) < method.slow_period + 2:
        raise RuntimeError(
            f"Not enough history for "
            f"{method.method_id}"
        )

    fast_alpha = ema_alpha(
        method.fast_period
    )

    slow_alpha = ema_alpha(
        method.slow_period
    )

    # Seed EMA from first close.
    fast_ema = closes[0]
    slow_ema = closes[0]

    for price in closes[1:]:
        fast_ema = (
            fast_alpha * price
            + (1.0 - fast_alpha) * fast_ema
        )

        slow_ema = (
            slow_alpha * price
            + (1.0 - slow_alpha) * slow_ema
        )

    method.previous_fast_ema = float(
        fast_ema
    )

    method.previous_slow_ema = float(
        slow_ema
    )

    # The historical final candle is treated as the previous
    # completed candle. The next live trade starts the new candle.
    last_timestamp = ny_time(
        df["timestamp"].iloc[-1]
    )

    method.candle_start = candle_bucket(
        last_timestamp,
        method.timeframe,
    )

    method.candle_end = timeframe_end(
        last_timestamp,
        method.timeframe,
    )

    method.candle_open = float(
        closes[-1]
    )

    method.candle_high = float(
        df["high"].iloc[-1]
    )

    method.candle_low = float(
        df["low"].iloc[-1]
    )

    method.candle_close = float(
        closes[-1]
    )

    # We do NOT use the historical candle as the current
    # forming candle. It becomes completed history.
    #
    # The next live candle gets a fresh threshold.
    method.entry_threshold = np.nan


def initialize_all_history():
    """
    Download each required timeframe directly from Alpaca.

    Example:
        1m method -> 1m request
        5m method -> 5m request
        30m method -> 30m request
        ...
    """

    symbols_by_timeframe = {}

    for timeframe, methods in TIMEFRAME_METHODS.items():

        symbols = sorted(
            {
                method.symbol
                for method in methods
            }
        )

        symbols_by_timeframe[
            timeframe
        ] = symbols

    for timeframe, symbols in symbols_by_timeframe.items():

        print()
        print(
            f"Downloading historical "
            f"{timeframe} data..."
        )

        cache = {}

        for symbol in symbols:

            print(
                f"  {symbol} {timeframe}"
            )

            df = download_historical(
                symbol,
                timeframe,
            )

            cache[symbol] = df

        for method in TIMEFRAME_METHODS[
            timeframe
        ]:

            df = cache[
                method.symbol
            ]

            initialize_method_from_history(
                method,
                df,
            )


# ============================================================
# LIVE CANDLE MANAGEMENT
# ============================================================

def finalize_current_candle(
    method: MethodState,
):
    """
    Finish the old candle and calculate the EMA values that
    will be used for the next candle.
    """

    close = method.candle_close

    if not np.isfinite(close):
        return

    method.previous_fast_ema = update_ema(
        method.previous_fast_ema,
        close,
        method.fast_period,
    )

    method.previous_slow_ema = update_ema(
        method.previous_slow_ema,
        close,
        method.slow_period,
    )


def start_new_candle(
    method: MethodState,
    timestamp: datetime,
    price: float,
):
    bucket = candle_bucket(
        timestamp,
        method.timeframe,
    )

    # Finalize the previous candle first.
    if method.candle_start is not None:
        finalize_current_candle(
            method
        )

    method.candle_start = bucket

    method.candle_end = bucket + timeframe_delta(
        method.timeframe
    )

    method.candle_open = price
    method.candle_high = price
    method.candle_low = price
    method.candle_close = price

    # Calculate the target ONCE for this new candle.
    method.entry_threshold = (
        calculate_entry_threshold(
            method.previous_fast_ema,
            method.previous_slow_ema,
            method.fast_period,
            method.slow_period,
        )
    )


def update_current_candle(
    method: MethodState,
    price: float,
):
    if not np.isfinite(
        method.candle_high
    ):
        method.candle_high = price
    else:
        method.candle_high = max(
            method.candle_high,
            price,
        )

    if not np.isfinite(
        method.candle_low
    ):
        method.candle_low = price
    else:
        method.candle_low = min(
            method.candle_low,
            price,
        )

    method.candle_close = price


# ============================================================
# ENTRY CHECK
# ============================================================

def should_enter(
    method: MethodState,
    price: float,
) -> bool:

    if method.in_trade:
        return False

    if method.order_pending:
        return False

    threshold = method.entry_threshold

    if not np.isfinite(threshold):
        return False

    # Bullish crossover only.
    return price >= threshold


# ============================================================
# ORDER PRICES
# ============================================================

def calculate_bracket_prices(
    entry_price: float,
    stop_loss_percent: float,
    risk_reward: float,
):

    stop_price = (
        entry_price
        * (1.0 - stop_loss_percent)
    )

    take_profit = (
        entry_price
        * (
            1.0
            + stop_loss_percent
            * risk_reward
        )
    )

    return (
        round(stop_price, 2),
        round(take_profit, 2),
    )


# ============================================================
# ORDER SUBMISSION
# ============================================================

def submit_entry(
    method: MethodState,
    trigger_price: float,
):
    """
    Submit a market entry with broker-managed TP/SL.

    The trigger price comes directly from the live trade stream.

    We deliberately do NOT use the stale historical candle close.
    """

    if method.in_trade:
        return

    if method.order_pending:
        return

    method.order_pending = True

    try:

        stop_price, take_profit = (
            calculate_bracket_prices(
                trigger_price,
                method.stop_loss_percent,
                method.risk_reward,
            )
        )

        print()
        print(
            f"SIGNAL | {method.method_id} | "
            f"{method.symbol} | "
            f"{method.timeframe} | "
            f"{method.strategy} | "
            f"price={trigger_price:.4f} | "
            f"threshold={method.entry_threshold:.4f}"
        )

        print(
            f"  stop={stop_price:.2f} "
            f"target={take_profit:.2f}"
        )

        order_request = MarketOrderRequest(
            symbol=method.symbol,
            qty=1,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(
                limit_price=take_profit,
            ),
            stop_loss=StopLossRequest(
                stop_price=stop_price,
            ),
        )

        order = TRADING_CLIENT.submit_order(
            order_request
        )

        method.parent_order_id = str(
            order.id
        )

        method.entry_order_id = str(
            order.id
        )

        print(
            f"ORDER ACCEPTED | "
            f"{method.method_id} | "
            f"{order.id}"
        )

        # Don't immediately call this a filled trade.
        # We wait for Alpaca's trade-update stream.

    except Exception as exc:

        # IMPORTANT:
        # An invalid/stale order must NOT kill the market
        # websocket.
        print(
            f"ORDER ERROR | "
            f"{method.method_id} | "
            f"{type(exc).__name__}: {exc}"
        )

        method.order_pending = False
        method.in_trade = False

    finally:

        # If the order was successfully submitted,
        # order_pending remains True until the broker reports
        # what happened.
        pass


# ============================================================
# TRADE STREAM
# ============================================================

async def on_trade(
    trade,
):
    """
    Continuous current-price handler.

    This is the important change.

    We do NOT wait for the 1-minute candle to close.

    Every live trade can:
      - update the current close
      - update high
      - update low
      - trigger an entry immediately
    """

    try:

        symbol = trade.symbol
        price = float(trade.price)

        timestamp = ny_time(
            trade.timestamp
        )

        if not np.isfinite(price):
            return

        with LOCK:

            LATEST_PRICES[
                symbol
            ] = price

            LATEST_PRICE_TIMESTAMPS[
                symbol
            ] = timestamp

            methods = METHODS_BY_SYMBOL.get(
                symbol,
                [],
            )

            if not methods:
                return

            for method in methods:

                current_bucket = candle_bucket(
                    timestamp,
                    method.timeframe,
                )

                # First live candle.
                if (
                    method.candle_start is None
                    or
                    current_bucket
                    != method.candle_start
                ):

                    start_new_candle(
                        method,
                        timestamp,
                        price,
                    )

                else:

                    update_current_candle(
                        method,
                        price,
                    )

                # Entry is checked AFTER the current price
                # updates the current candle.
                if should_enter(
                    method,
                    price,
                ):

                    # Submit immediately.
                    submit_entry(
                        method,
                        price,
                    )

    except Exception as exc:

        print(
            f"TRADE HANDLER ERROR | "
            f"{type(exc).__name__}: {exc}"
        )


# ============================================================
# QUOTE STREAM
# ============================================================

async def on_quote(
    quote,
):
    """
    Quote stream is kept available for the latest bid/ask.

    Strategy triggering itself uses actual trade prices.
    """

    try:

        symbol = quote.symbol

        timestamp = ny_time(
            quote.timestamp
        )

        bid = float(
            quote.bid_price
        )

        ask = float(
            quote.ask_price
        )

        # This is intentionally NOT used to alter OHLC.
        # OHLC is trade-price based.
        #
        # We keep it available for diagnostics / order
        # validation if needed.

        if np.isfinite(bid) and np.isfinite(ask):

            pass

    except Exception as exc:

        print(
            f"QUOTE HANDLER ERROR | "
            f"{type(exc).__name__}: {exc}"
        )


# ============================================================
# BROKER TRADE UPDATES
# ============================================================

def find_method_by_order_id(
    order_id: str,
):
    for method in METHODS.values():

        if method.parent_order_id == order_id:
            return method

        if method.entry_order_id == order_id:
            return method

        if method.take_profit_order_id == order_id:
            return method

        if method.stop_loss_order_id == order_id:
            return method

    return None


def update_equity_after_trade(
    method: MethodState,
    entry_price: float,
    exit_price: float,
):
    if entry_price <= 0:
        return

    return_decimal = (
        exit_price / entry_price
    ) - 1.0

    method.equity *= (
        1.0 + return_decimal
    )

    method.equity = round(
        method.equity,
        3,
    )

    print()
    print(
        f"TRADE COMPLETE | "
        f"{method.method_id}"
    )

    print(
        f"  entry={entry_price:.4f}"
    )

    print(
        f"  exit={exit_price:.4f}"
    )

    print(
        f"  return={return_decimal * 100:.4f}%"
    )

    print(
        f"  equity={method.equity:.3f}"
    )

    # Save the updated equity curve.
    save_live_equity(
        method
    )


def save_live_equity(
    method: MethodState,
):
    """
    Save the latest equity state.

    This uses the live_equity/{method_id}.parquet convention.
    """

    try:

        if hasattr(
            storage,
            "save_live_equity",
        ):

            storage.save_live_equity(
                method.method_id,
                method.equity,
            )

        elif hasattr(
            storage,
            "save_equity",
        ):

            storage.save_equity(
                method.method_id,
                method.equity,
            )

        else:

            print(
                f"WARNING | No live-equity "
                f"save function found in storage.py"
            )

    except Exception as exc:

        print(
            f"EQUITY SAVE ERROR | "
            f"{method.method_id} | "
            f"{type(exc).__name__}: {exc}"
        )


# ============================================================
# EXISTING EQUITY
# ============================================================

def load_live_equity(
    method: MethodState,
):
    try:

        if hasattr(
            storage,
            "load_live_equity",
        ):

            value = storage.load_live_equity(
                method.method_id
            )

            if value is not None:
                method.equity = float(
                    value
                )

        elif hasattr(
            storage,
            "get_live_equity",
        ):

            value = storage.get_live_equity(
                method.method_id
            )

            if value is not None:
                method.equity = float(
                    value
                )

    except Exception as exc:

        print(
            f"EQUITY LOAD WARNING | "
            f"{method.method_id} | "
            f"{exc}"
        )


def load_all_equity():
    for method in METHODS.values():

        method.equity = STARTING_EQUITY

        load_live_equity(
            method
        )

        print(
            f"EQUITY | "
            f"{method.method_id} | "
            f"{method.equity:.3f}"
        )


# ============================================================
# ALPACA TRADE UPDATE CALLBACK
# ============================================================

async def on_trade_update(
    update,
):
    """
    Handle broker order updates.

    Entry:
        wait for fill -> store actual fill price.

    Exit:
        TP/SL leg fills -> calculate actual trade return
        and update that method's equity.
    """

    try:

        event = getattr(
            update,
            "event",
            None,
        )

        order = getattr(
            update,
            "order",
            None,
        )

        if order is None:
            return

        order_id = str(
            getattr(
                order,
                "id",
                "",
            )
        )

        method = find_method_by_order_id(
            order_id
        )

        if method is None:
            return

        status = str(
            getattr(
                order,
                "status",
                "",
            )
        ).lower()

        side = str(
            getattr(
                order,
                "side",
                "",
            )
        ).lower()

        filled_price = getattr(
            order,
            "filled_avg_price",
            None,
        )

        if filled_price is not None:
            try:
                filled_price = float(
                    filled_price
                )
            except Exception:
                filled_price = None

        print(
            f"ORDER UPDATE | "
            f"{method.method_id} | "
            f"event={event} | "
            f"status={status} | "
            f"side={side} | "
            f"price={filled_price}"
        )

        # ----------------------------------------------------
        # ENTRY FILLED
        # ----------------------------------------------------

        if (
            side == "buy"
            and status == "filled"
        ):

            method.in_trade = True
            method.order_pending = False

            method.entry_price = (
                filled_price
            )

            method.entry_order_id = (
                order_id
            )

            # Alpaca bracket orders have child legs.
            legs = getattr(
                order,
                "legs",
                None,
            )

            if legs:

                for leg in legs:

                    leg_id = str(
                        getattr(
                            leg,
                            "id",
                            "",
                        )
                    )

                    leg_type = str(
                        getattr(
                            leg,
                            "type",
                            "",
                        )
                    ).lower()

                    if (
                        "limit" in leg_type
                    ):
                        method.take_profit_order_id = (
                            leg_id
                        )

                    elif (
                        "stop" in leg_type
                    ):
                        method.stop_loss_order_id = (
                            leg_id
                        )

            print(
                f"ENTRY FILLED | "
                f"{method.method_id} | "
                f"entry={method.entry_price}"
            )

            return

        # ----------------------------------------------------
        # EXIT FILLED
        # ----------------------------------------------------

        if (
            side == "sell"
            and status == "filled"
        ):

            if method.entry_price is None:
                print(
                    f"WARNING | Exit filled but "
                    f"entry price missing | "
                    f"{method.method_id}"
                )

                method.in_trade = False
                method.order_pending = False

                return

            exit_price = filled_price

            if exit_price is None:

                print(
                    f"WARNING | Exit fill has no "
                    f"filled_avg_price | "
                    f"{method.method_id}"
                )

                return

            update_equity_after_trade(
                method,
                method.entry_price,
                exit_price,
            )

            method.in_trade = False
            method.order_pending = False

            method.entry_order_id = None
            method.parent_order_id = None
            method.take_profit_order_id = None
            method.stop_loss_order_id = None
            method.entry_price = None

            return

        # ----------------------------------------------------
        # REJECTED / CANCELED ENTRY
        # ----------------------------------------------------

        if status in {
            "rejected",
            "canceled",
            "expired",
            "done_for_day",
        }:

            if not method.in_trade:

                method.order_pending = False
                method.in_trade = False

                method.entry_order_id = None
                method.parent_order_id = None

                print(
                    f"ENTRY NOT COMPLETED | "
                    f"{method.method_id} | "
                    f"{status}"
                )

    except Exception as exc:

        print(
            f"TRADE UPDATE ERROR | "
            f"{type(exc).__name__}: {exc}"
        )


# ============================================================
# STREAM SETUP
# ============================================================

def start_market_stream():
    symbols = sorted(
        METHODS_BY_SYMBOL.keys()
    )

    if not symbols:
        raise RuntimeError(
            "No symbols available for market stream."
        )

    print()
    print(
        "Starting Alpaca market-data stream..."
    )

    print(
        "Symbols:",
        ", ".join(symbols),
    )

    # --------------------------------------------------------
    # CURRENT PRICE
    #
    # THIS IS THE IMPORTANT PART:
    #
    # Trades are used for continuous pricing.
    # --------------------------------------------------------

    STREAM.subscribe_trades(
        on_trade,
        *symbols,
    )

    # Quotes are also subscribed to so the system has
    # continuous bid/ask information available.
    STREAM.subscribe_quotes(
        on_quote,
        *symbols,
    )

    print(
        "Subscribed to live trades."
    )

    print(
        "Subscribed to live quotes."
    )

    print(
        "Waiting for live prices..."
    )

    # This call blocks.
    STREAM.run()


# ============================================================
# BROKER UPDATES
# ============================================================

def start_trade_update_stream():
    """
    Run the Alpaca trading-update websocket separately from
    the market-data websocket.

    This allows market data to continue even if an order
    is rejected.
    """

    from alpaca.trading.stream import TradingStream

    trading_stream = TradingStream(
        API_KEY,
        SECRET_KEY,
        paper=PAPER,
    )

    trading_stream.subscribe_trade_updates(
        on_trade_update
    )

    print(
        "Starting Alpaca trade-update stream..."
    )

    trading_stream.run()


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 70)
    print("LIVE TRADING SYSTEM")
    print("=" * 70)
    print()

    print(
        "Timezone:",
        "America/New_York",
    )

    print(
        "Starting equity:",
        STARTING_EQUITY,
    )

    print(
        "Top methods:",
        TOP_METHODS_R2_KEY,
    )

    print()

    # --------------------------------------------------------
    # 1. LOAD TOP 100 METHODS
    # --------------------------------------------------------

    build_methods()

    # --------------------------------------------------------
    # 2. LOAD EXISTING EQUITY
    # --------------------------------------------------------

    load_all_equity()

    # --------------------------------------------------------
    # 3. DOWNLOAD HISTORICAL DATA
    #
    # Each timeframe is requested DIRECTLY from Alpaca.
    # --------------------------------------------------------

    initialize_all_history()

    print()
    print(
        "Historical initialization complete."
    )

    # --------------------------------------------------------
    # 4. START BROKER UPDATE STREAM
    # --------------------------------------------------------

    broker_thread = threading.Thread(
        target=start_trade_update_stream,
        daemon=True,
    )

    broker_thread.start()

    # --------------------------------------------------------
    # 5. START LIVE MARKET STREAM
    #
    # This blocks.
    # --------------------------------------------------------

    while True:

        try:

            start_market_stream()

        except KeyboardInterrupt:

            print()
            print(
                "Stopping live trader..."
            )

            break

        except Exception as exc:

            # Never permanently kill the trader because
            # a websocket disconnected.
            print()
            print(
                f"MARKET STREAM ERROR | "
                f"{type(exc).__name__}: {exc}"
            )

            print(
                "Restarting market stream in 5 seconds..."
            )

            time.sleep(5)


if __name__ == "__main__":
    main()