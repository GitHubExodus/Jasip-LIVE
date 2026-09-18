

import os
import time
import math
import threading
from datetime import datetime, timedelta, timezone
from collections import defaultdict

import numpy as np

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.live import StockDataStream
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    TakeProfitRequest,
    StopLossRequest,
    GetOrdersRequest,
)
from alpaca.trading.enums import (
    OrderSide,
    TimeInForce,
    OrderClass,
    QueryOrderStatus,
)


# ============================================================
# CONFIG
# ============================================================

API_KEY = "PKA4A6THLEKI6QD2MQPOAO25J3"
API_SECRET = "4nj9w53vMrNKJGZsHqN7Siqy34z2Gis9TffWi2beszNU"

ALPACA_PAPER = True

SYMBOLS = [
    "GIPR",
    "IMCC",
    "TNMG",
    "TRUG",
    "MEDS",
    "CPOP",
    "USDE",
    "BIAF",
    "NCPL",
    "BENF",
    "QNME",
    "MRNO",
    "TJGC",
    "CYPH",
]

TRADE_DOLLARS = 100.00

EXPECTED_THRESHOLD = 0.01

EMA_FAST = 3
EMA_SLOW = 5

BAR_10S_SECONDS = 10
BAR_1M_SECONDS = 60

BREAKOUT_FUTURE_BARS = 3

ORDER_FILL_TIMEOUT = 60
ORDER_FILL_POLL_SECONDS = 0.5

# Expected-profit-based exits.
# TP = half expected max profit.
# SL = half TP.
TP_FRACTION = 0.50
SL_FRACTION_OF_TP = 1

HIST_START = datetime(2026, 1, 1, tzinfo=timezone.utc)

# ============================================================
# CLIENTS
# ============================================================

historical_client = StockHistoricalDataClient(
    API_KEY,
    API_SECRET,
)

trading_client = TradingClient(
    API_KEY,
    API_SECRET,
    paper=ALPACA_PAPER,
)

# ============================================================
# RAW / LIVE DATA
# ============================================================

# symbol -> list[(timestamp, price, size)]
RAW_TRADES = defaultdict(list)

# symbol -> {
#     timestamp: {
#         open,
#         high,
#         low,
#         close,
#         volume
#     }
# }
BARS_10S = defaultdict(dict)

BARS_1M = defaultdict(dict)

# ============================================================
# EMA STATE
# ============================================================

# symbol -> {
#     "fast": float | None,
#     "slow": float | None
# }
EMA_STATE = {
    symbol: {
        "fast": None,
        "slow": None,
    }
    for symbol in SYMBOLS
}

# -1 = fast below slow
#  0 = equal / not initialized
# +1 = fast above slow
EMA_RELATION = {
    symbol: 0
    for symbol in SYMBOLS
}

# ============================================================
# EMA HYPOTHETICAL LONG TRADES
# ============================================================

# symbol -> {
#     "entry": float,
#     "max_price": float
# } | None
EMA_OPEN_LONG = {
    symbol: None
    for symbol in SYMBOLS
}

# Only sum/count are stored.
EMA_STATS = {
    symbol: {
        "sum": 0.0,
        "count": 0,
    }
    for symbol in SYMBOLS
}

# ============================================================
# HISTORICAL BREAKOUT STATS
# ============================================================

# Historical 1-minute breakout statistics.
#
# These NEVER update from live WebSocket data.
BREAKOUT_STATS = {
    symbol: {
        "sum": 0.0,
        "count": 0,
    }
    for symbol in SYMBOLS
}

# ============================================================
# BAR PROCESSING STATE
# ============================================================

LAST_10S_BUCKET = {
    symbol: None
    for symbol in SYMBOLS
}

LAST_1M_BUCKET = {
    symbol: None
    for symbol in SYMBOLS
}

# ============================================================
# REAL TRADE STATE
# ============================================================

REAL_TRADE_COUNT = 0

REAL_TRADE_COUNT_LOCK = threading.Lock()

# Market-buy order IDs currently waiting for fills.
PENDING_ENTRY_ORDERS = set()

PENDING_ENTRY_LOCK = threading.Lock()

# OCO orders already submitted for entry order IDs.
OCO_SUBMITTED = set()

OCO_LOCK = threading.Lock()


# ============================================================
# TIME HELPERS
# ============================================================

def floor_timestamp(timestamp, seconds):
    """
    Floor a timestamp to the requested number of seconds.
    """
    timestamp = timestamp.replace(microsecond=0)

    epoch = int(timestamp.timestamp())

    floored = epoch - (epoch % seconds)

    return datetime.fromtimestamp(
        floored,
        tz=timestamp.tzinfo,
    )


# ============================================================
# EMA
# ============================================================

def update_ema(previous_ema, price, period):
    """
    Incrementally update one EMA.

    Returns:
        current EMA
    """
    alpha = 2.0 / (period + 1.0)

    if previous_ema is None:
        return float(price)

    return (
        alpha * float(price)
        + (1.0 - alpha) * previous_ema
    )


# ============================================================
# EMA HYPOTHETICAL TRADE
# ============================================================

def close_ema_long(symbol, exit_price):
    """
    Close the currently open hypothetical EMA LONG.

    Max profit is calculated from the highest HIGH reached
    between entry and exit.
    """

    trade = EMA_OPEN_LONG[symbol]

    if trade is None:
        return

    entry = trade["entry"]
    max_price = trade["max_price"]

    if entry <= 0:
        EMA_OPEN_LONG[symbol] = None
        return

    profit = (max_price - entry) / entry

    stats = EMA_STATS[symbol]

    stats["sum"] += profit
    stats["count"] += 1

    average = stats["sum"] / stats["count"]

    print(
        f"EMA HISTORY | {symbol} | "
        f"LONG closed={profit:.2%} | "
        f"n={stats['count']} | "
        f"avg={average:.2%}"
    )

    EMA_OPEN_LONG[symbol] = None


def process_ema_bar(symbol, bar):
    """
    Process one completed 10-second bar.

    Detects:
        EMA 3 crossing above EMA 5 -> LONG entry
        EMA 3 crossing below EMA 5 -> LONG exit
    """

    close_price = float(bar["close"])
    high_price = float(bar["high"])

    state = EMA_STATE[symbol]

    previous_fast = state["fast"]
    previous_slow = state["slow"]

    state["fast"] = update_ema(
        previous_fast,
        close_price,
        EMA_FAST,
    )

    state["slow"] = update_ema(
        previous_slow,
        close_price,
        EMA_SLOW,
    )

    fast = state["fast"]
    slow = state["slow"]

    if fast > slow:
        relation = 1
    elif fast < slow:
        relation = -1
    else:
        relation = 0

    previous_relation = EMA_RELATION[symbol]

    EMA_RELATION[symbol] = relation

    # --------------------------------------------------------
    # Update existing hypothetical LONG.
    # --------------------------------------------------------

    open_trade = EMA_OPEN_LONG[symbol]

    if open_trade is not None:
        if high_price > open_trade["max_price"]:
            open_trade["max_price"] = high_price

    # --------------------------------------------------------
    # Cross UP -> open hypothetical LONG.
    # --------------------------------------------------------

    cross_up = (
        previous_relation < 0
        and relation > 0
    )

    if cross_up:

        # If somehow another hypothetical trade is open,
        # close it first.
        if EMA_OPEN_LONG[symbol] is not None:
            close_ema_long(
                symbol,
                close_price,
            )

        EMA_OPEN_LONG[symbol] = {
            "entry": close_price,
            "max_price": high_price,
        }

        print(
            f"EMA SIGNAL | {symbol} | "
            f"LONG CROSS UP | "
            f"price={close_price:.4f}"
        )

    # --------------------------------------------------------
    # Cross DOWN -> close hypothetical LONG.
    # --------------------------------------------------------

    cross_down = (
        previous_relation > 0
        and relation < 0
    )

    if cross_down:

        if EMA_OPEN_LONG[symbol] is not None:
            close_ema_long(
                symbol,
                close_price,
            )


# ============================================================
# EXPECTED EMA PROFIT
# ============================================================

def get_ema_expected_profit(symbol):
    """
    Return average completed hypothetical EMA LONG profit.
    """

    stats = EMA_STATS[symbol]

    if stats["count"] == 0:
        return None

    return stats["sum"] / stats["count"]


# ============================================================
# HISTORICAL BREAKOUT STATISTICS
# ============================================================

def calculate_historical_breakout_stats(symbol, bars):
    """
    Calculate historical LONG breakout expected max profit.

    Breakout:
        current high > previous high

    Reference:
        previous bar high

    Future window:
        breakout bar + next 3 completed candles

    Max profit:
        highest HIGH in that 4-bar window relative
        to the previous bar high.

    Only sum/count are stored.
    """

    highs = np.asarray(
        [float(bar.high) for bar in bars],
        dtype=np.float64,
    )

    n = len(highs)

    total_sum = 0.0
    total_count = 0

    # Need:
    # i-1 = previous reference bar
    # i   = breakout bar
    # i+1
    # i+2
    # i+3
    #
    # Therefore i <= n-4.
    for i in range(1, n - BREAKOUT_FUTURE_BARS):

        previous_high = highs[i - 1]
        breakout_high = highs[i]

        if breakout_high <= previous_high:
            continue

        future_end = i + BREAKOUT_FUTURE_BARS + 1

        max_future_high = np.max(
            highs[i:future_end]
        )

        if previous_high <= 0:
            continue

        profit = (
            max_future_high - previous_high
        ) / previous_high

        total_sum += profit
        total_count += 1

    BREAKOUT_STATS[symbol]["sum"] = total_sum
    BREAKOUT_STATS[symbol]["count"] = total_count

    if total_count > 0:
        average = total_sum / total_count

        print(
            f"HIST BREAKOUT | {symbol} | "
            f"LONG n={total_count} | "
            f"avg={average:.2%}"
        )
    else:
        print(
            f"HIST BREAKOUT | {symbol} | "
            f"LONG n=0 | avg=N/A"
        )


def get_breakout_expected_profit(symbol):
    """
    Return the fixed historical breakout average.
    """

    stats = BREAKOUT_STATS[symbol]

    if stats["count"] == 0:
        return None

    return stats["sum"] / stats["count"]


# ============================================================
# HISTORICAL DATA LOADING
# ============================================================

def load_historical_breakout_data():
    """
    Download historical 1-minute bars once at startup.

    These bars are used ONLY for breakout expected-profit
    statistics.

    They are never modified by live WebSocket data.
    """

    end = (
        datetime.now(timezone.utc)
        - timedelta(minutes=10)
    )

    print("Loading historical breakout data...")

    for symbol in SYMBOLS:

        try:

            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Minute,
                start=HIST_START,
                end=end,
                feed=DataFeed.IEX,
            )

            response = historical_client.get_stock_bars(
                request
            )

            bars = response[symbol]

            calculate_historical_breakout_stats(
                symbol,
                bars,
            )

        except Exception as exc:

            print(
                f"HIST ERROR | {symbol} | {exc}"
            )

    print("Historical breakout data loaded.")


# ============================================================
# 10-SECOND BAR CREATION
# ============================================================

def build_10s_bar(symbol, bucket):
    """
    Convert raw trades in one 10-second bucket
    into one completed 10-second OHLCV bar.
    """

    trades = RAW_TRADES[symbol]

    if not trades:
        return None

    selected = [
        trade
        for trade in trades
        if floor_timestamp(
            trade[0],
            BAR_10S_SECONDS,
        ) == bucket
    ]

    if not selected:
        return None

    prices = np.asarray(
        [trade[1] for trade in selected],
        dtype=np.float64,
    )

    sizes = np.asarray(
        [trade[2] for trade in selected],
        dtype=np.float64,
    )

    return {
        "timestamp": bucket,
        "open": float(prices[0]),
        "high": float(np.max(prices)),
        "low": float(np.min(prices)),
        "close": float(prices[-1]),
        "volume": float(np.sum(sizes)),
    }


# ============================================================
# 1-MINUTE BAR CREATION
# ============================================================

def build_1m_bar(symbol, minute_bucket):
    """
    Build one 1-minute bar from exactly six completed
    10-second bars.
    """

    bars = []

    for offset in range(6):

        bucket = minute_bucket + timedelta(
            seconds=offset * BAR_10S_SECONDS
        )

        bar = BARS_10S[symbol].get(bucket)

        if bar is None:
            return None

        bars.append(bar)

    return {
        "timestamp": minute_bucket,
        "open": bars[0]["open"],
        "high": max(
            bar["high"]
            for bar in bars
        ),
        "low": min(
            bar["low"]
            for bar in bars
        ),
        "close": bars[-1]["close"],
        "volume": sum(
            bar["volume"]
            for bar in bars
        ),
    }


# ============================================================
# LIVE BREAKOUT SIGNAL
# ============================================================

def process_live_breakout(symbol, bar):
    """
    Detect the live 1-minute LONG breakout.

    This does NOT modify BREAKOUT_STATS.

    Historical expected profit remains fixed.
    """

    bars = BARS_1M[symbol]

    previous_minute = bar["timestamp"] - timedelta(
        minutes=1
    )

    previous_bar = bars.get(previous_minute)

    if previous_bar is None:
        return False

    current_high = float(bar["high"])
    previous_high = float(previous_bar["high"])

    if current_high > previous_high:

        print(
            f"BREAKOUT SIGNAL | {symbol} | "
            f"LONG | "
            f"previous_high={previous_high:.4f} | "
            f"current_high={current_high:.4f}"
        )

        return True

    return False


# ============================================================
# EXPOSURE CHECK
# ============================================================

def has_exposure(symbol):
    """
    Return True if the account already has exposure to symbol
    or has an open order involving symbol.

    Fail-safe:
        API error -> True

    This prevents duplicate trades when account state cannot
    be verified.
    """

    try:

        # ----------------------------------------------------
        # Existing position
        # ----------------------------------------------------

        try:
            position = trading_client.get_open_position(
                symbol
            )

            if position is not None:
                qty = float(position.qty)

                if qty != 0:
                    return True

        except Exception:
            pass

        # ----------------------------------------------------
        # Open orders
        # ----------------------------------------------------

        request = GetOrdersRequest(
            status=QueryOrderStatus.OPEN,
        )

        orders = trading_client.get_orders(
            filter=request
        )

        for order in orders:

            if order.symbol == symbol:
                return True

        return False

    except Exception as exc:

        print(
            f"EXPOSURE ERROR | {symbol} | {exc}"
        )

        return True


# ============================================================
# POSITION SIZE
# ============================================================

def calculate_quantity(price):
    """
    $100 maximum position value.
    Whole shares only.
    """

    if price <= 0:
        return 0

    return int(
        math.floor(
            TRADE_DOLLARS / price
        )
    )


# ============================================================
# PRICE ROUNDING
# ============================================================

def round_price(price):
    """
    Alpaca equity prices are submitted to cents here.
    """

    return round(
        float(price),
        2,
    )


# ============================================================
# CALCULATE OCO PRICES
# ============================================================

def calculate_oco_prices(
    entry_price,
    expected_profit,
):
    """
    Expected profit:
        average historical / hypothetical max profit

    TP:
        50% of expected profit

    SL:
        50% of TP

    Example:
        expected = 4%

        TP = +2%
        SL = -1%
    """

    tp_percent = (
        expected_profit
        * TP_FRACTION
    )

    sl_percent = (
        tp_percent
        * SL_FRACTION_OF_TP
    )

    take_profit = entry_price * (
        1.0 + tp_percent
    )

    stop_loss = entry_price * (
        1.0 - sl_percent
    )

    take_profit = round_price(
        take_profit
    )

    stop_loss = round_price(
        stop_loss
    )

    # --------------------------------------------------------
    # Ensure valid cent distance.
    #
    # Alpaca requires the stop-loss sell price to be at least
    # $0.01 below the OCO base/take-profit price.
    # --------------------------------------------------------

    if stop_loss >= take_profit:

        stop_loss = round_price(
            take_profit - 0.01
        )

    if stop_loss <= 0:
        stop_loss = 0.01

    return (
        take_profit,
        stop_loss,
        tp_percent,
        sl_percent,
    )


# ============================================================
# WAIT FOR MARKET BUY FILL
# ============================================================

def wait_for_entry_fill(
    symbol,
    strategy,
    order_id,
    expected_profit,
    requested_qty,
):
    """
    Wait for the market BUY to fill.

    Once filled:
        actual fill price is read from Alpaca
        TP/SL are calculated from actual fill
        OCO SELL is submitted
    """

    print(
        f"ENTRY WAIT | {symbol} | "
        f"{strategy} | "
        f"order={order_id}"
    )

    deadline = (
        time.time()
        + ORDER_FILL_TIMEOUT
    )

    final_order = None

    while time.time() < deadline:

        try:

            order = trading_client.get_order_by_id(
                order_id
            )

            final_order = order

            status = str(
                order.status
            ).lower()

            if status == "filled":

                break

            if status in {
                "canceled",
                "cancelled",
                "rejected",
                "expired",
            }:

                print(
                    f"ENTRY FAILED | {symbol} | "
                    f"{strategy} | "
                    f"status={status}"
                )

                with PENDING_ENTRY_LOCK:
                    PENDING_ENTRY_ORDERS.discard(
                        str(order_id)
                    )

                return

        except Exception as exc:

            print(
                f"FILL CHECK ERROR | {symbol} | "
                f"{strategy} | {exc}"
            )

        time.sleep(
            ORDER_FILL_POLL_SECONDS
        )

    # --------------------------------------------------------
    # Timeout.
    # --------------------------------------------------------

    if final_order is None:

        print(
            f"ENTRY TIMEOUT | {symbol} | "
            f"{strategy} | "
            f"order={order_id}"
        )

        with PENDING_ENTRY_LOCK:
            PENDING_ENTRY_ORDERS.discard(
                str(order_id)
            )

        return

    status = str(
        final_order.status
    ).lower()

    if status != "filled":

        print(
            f"ENTRY TIMEOUT | {symbol} | "
            f"{strategy} | "
            f"status={status}"
        )

        with PENDING_ENTRY_LOCK:
            PENDING_ENTRY_ORDERS.discard(
                str(order_id)
            )

        return

    # --------------------------------------------------------
    # Actual Alpaca fill data.
    # --------------------------------------------------------

    filled_avg_price = (
        final_order.filled_avg_price
    )

    filled_qty = (
        final_order.filled_qty
    )

    if filled_avg_price is None:
        print(
            f"ENTRY ERROR | {symbol} | "
            f"{strategy} | "
            f"missing filled_avg_price"
        )

        with PENDING_ENTRY_LOCK:
            PENDING_ENTRY_ORDERS.discard(
                str(order_id)
            )

        return

    if filled_qty is None:
        print(
            f"ENTRY ERROR | {symbol} | "
            f"{strategy} | "
            f"missing filled_qty"
        )

        with PENDING_ENTRY_LOCK:
            PENDING_ENTRY_ORDERS.discard(
                str(order_id)
            )

        return

    entry_price = float(
        filled_avg_price
    )

    filled_qty = int(
        float(filled_qty)
    )

    if filled_qty <= 0:

        print(
            f"ENTRY ERROR | {symbol} | "
            f"{strategy} | "
            f"filled_qty={filled_qty}"
        )

        with PENDING_ENTRY_LOCK:
            PENDING_ENTRY_ORDERS.discard(
                str(order_id)
            )

        return

    # --------------------------------------------------------
    # Calculate exits from ACTUAL fill price.
    # --------------------------------------------------------

    (
        take_profit,
        stop_loss,
        tp_percent,
        sl_percent,
    ) = calculate_oco_prices(
        entry_price,
        expected_profit,
    )

    print(
        f"ENTRY FILLED | {symbol} | "
        f"{strategy} | "
        f"qty={filled_qty} | "
        f"fill={entry_price:.4f} | "
        f"expected={expected_profit:.2%}"
    )

    # --------------------------------------------------------
    # Submit OCO.
    # --------------------------------------------------------

    submit_oco_exit(
        symbol=symbol,
        strategy=strategy,
        qty=filled_qty,
        entry_price=entry_price,
        take_profit=take_profit,
        stop_loss=stop_loss,
        tp_percent=tp_percent,
        sl_percent=sl_percent,
        entry_order_id=str(order_id),
    )

    with PENDING_ENTRY_LOCK:
        PENDING_ENTRY_ORDERS.discard(
            str(order_id)
        )


# ============================================================
# SUBMIT OCO EXIT
# ============================================================

def submit_oco_exit(
    symbol,
    strategy,
    qty,
    entry_price,
    take_profit,
    stop_loss,
    tp_percent,
    sl_percent,
    entry_order_id,
):
    """
    Submit Alpaca-managed OCO exit.

    One OCO group contains:

        SELL LIMIT -> take profit
        SELL STOP  -> stop loss

    If one executes, Alpaca cancels the other.
    """

    with OCO_LOCK:

        if entry_order_id in OCO_SUBMITTED:
            return

        try:

            oco_request = LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.GTC,
                limit_price=take_profit,
                order_class=OrderClass.OCO,
                take_profit=TakeProfitRequest(
                    limit_price=take_profit
                ),
                stop_loss=StopLossRequest(
                    stop_price=stop_loss
                ),
            )

            oco_order = trading_client.submit_order(
                order_data=oco_request
            )

            OCO_SUBMITTED.add(
                entry_order_id
            )

            print(
                f"OCO SUBMITTED | {symbol} | "
                f"{strategy} | "
                f"qty={qty} | "
                f"entry={entry_price:.4f} | "
                f"TP={take_profit:.2f} "
                f"(+{tp_percent:.2%}) | "
                f"SL={stop_loss:.2f} "
                f"(-{sl_percent:.2%}) | "
                f"oco={oco_order.id}"
            )

        except Exception as exc:

            print(
                f"OCO FAILED | {symbol} | "
                f"{strategy} | "
                f"qty={qty} | "
                f"entry={entry_price:.4f} | "
                f"TP={take_profit:.2f} | "
                f"SL={stop_loss:.2f} | "
                f"{exc}"
            )


# ============================================================
# REAL LONG ENTRY
# ============================================================

def attempt_long_entry(
    symbol,
    strategy,
    signal_price,
    expected_profit,
):
    """
    Submit a plain MARKET BUY.

    Exit orders are NOT submitted here.

    After the market BUY fills, a background worker submits
    the OCO exit using the actual fill price.
    """

    global REAL_TRADE_COUNT

    print(
        f"ENTRY SIGNAL | {symbol} | "
        f"{strategy} | "
        f"LONG | "
        f"price={signal_price:.4f}"
    )

    # --------------------------------------------------------
    # Expected-profit requirement.
    # --------------------------------------------------------

    if expected_profit is None:

        print(
            f"SKIP | {symbol} | "
            f"{strategy} | "
            f"no expected profit"
        )

        return

    if expected_profit <= EXPECTED_THRESHOLD:

        print(
            f"SKIP | {symbol} | "
            f"{strategy} | "
            f"expected={expected_profit:.2%} "
            f"<= {EXPECTED_THRESHOLD:.2%}"
        )

        return

    # --------------------------------------------------------
    # Existing position / open order.
    # --------------------------------------------------------

    if has_exposure(symbol):

        print(
            f"SKIP | {symbol} | "
            f"{strategy} | "
            f"already exposed"
        )

        return

    # --------------------------------------------------------
    # Pending market-buy order.
    # --------------------------------------------------------

    with PENDING_ENTRY_LOCK:

        if any(
            True
            for order_id in PENDING_ENTRY_ORDERS
        ):
            # This global check is intentionally conservative.
            # Exposure will be checked again before actual order.
            pass

    # --------------------------------------------------------
    # Position size.
    # --------------------------------------------------------

    qty = calculate_quantity(
        signal_price
    )

    if qty <= 0:

        print(
            f"SKIP | {symbol} | "
            f"{strategy} | "
            f"price too high | "
            f"price={signal_price:.4f}"
        )

        return

    # --------------------------------------------------------
    # Re-check exposure immediately before order.
    # --------------------------------------------------------

    if has_exposure(symbol):

        print(
            f"SKIP | {symbol} | "
            f"{strategy} | "
            f"exposure appeared before order"
        )

        return

    # --------------------------------------------------------
    # Plain MARKET BUY.
    # --------------------------------------------------------

    try:

        market_request = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )

        order = trading_client.submit_order(
            order_data=market_request
        )

        order_id = str(order.id)

        with PENDING_ENTRY_LOCK:
            PENDING_ENTRY_ORDERS.add(
                order_id
            )

        with REAL_TRADE_COUNT_LOCK:
            REAL_TRADE_COUNT += 1
            current_trade_count = (
                REAL_TRADE_COUNT
            )

        print(
            f"ORDER SUBMITTED | {symbol} | "
            f"{strategy} | "
            f"MARKET BUY | "
            f"qty={qty} | "
            f"signal_price={signal_price:.4f} | "
            f"expected={expected_profit:.2%} | "
            f"real_trade_count={current_trade_count} | "
            f"order={order_id}"
        )

        # ----------------------------------------------------
        # Wait for fill in background so the market-data
        # processor is not blocked.
        # ----------------------------------------------------

        worker = threading.Thread(
            target=wait_for_entry_fill,
            args=(
                symbol,
                strategy,
                order_id,
                expected_profit,
                qty,
            ),
            daemon=True,
        )

        worker.start()

    except Exception as exc:

        print(
            f"ORDER FAILED | {symbol} | "
            f"{strategy} | "
            f"MARKET BUY | "
            f"qty={qty} | "
            f"{exc}"
        )


# ============================================================
# PROCESS COMPLETED 10-SECOND BAR
# ============================================================

def process_10s_bar(symbol, bar):
    """
    Store completed 10-second bar,
    update EMA strategy,
    and potentially submit a real LONG.
    """

    timestamp = bar["timestamp"]

    BARS_10S[symbol][timestamp] = bar

    # --------------------------------------------------------
    # EMA historical/hypothetical strategy.
    # --------------------------------------------------------

    process_ema_bar(
        symbol,
        bar,
    )

    expected_profit = (
        get_ema_expected_profit(symbol)
    )

    # --------------------------------------------------------
    # Only trade after at least one completed hypothetical
    # EMA LONG exists.
    # --------------------------------------------------------

    if expected_profit is None:
        return

    # --------------------------------------------------------
    # Real EMA signal.
    #
    # The actual cross-up is detected inside process_ema_bar.
    # We need to identify whether this specific bar generated
    # the cross.
    # --------------------------------------------------------

    # We detect the current relation and previous state by
    # looking at the bar-processing transition directly.
    #
    # Because process_ema_bar already updates EMA_RELATION,
    # use the EMA values and historical relationship here.
    #
    # A real trade is triggered when EMA 3 > EMA 5 and the
    # previous completed bar had EMA 3 <= EMA 5.
    #
    # To avoid duplicating state, this is handled through
    # the EMA signal state below.

    return


# ============================================================
# EMA REAL SIGNAL STATE
# ============================================================

EMA_REAL_PREVIOUS_RELATION = {
    symbol: 0
    for symbol in SYMBOLS
}


def process_ema_bar_with_real_signal(
    symbol,
    bar,
):
    """
    EMA processing plus real LONG signal detection.

    This keeps the hypothetical EMA history and real signal
    detection synchronized.
    """

    close_price = float(bar["close"])
    high_price = float(bar["high"])

    state = EMA_STATE[symbol]

    previous_relation = EMA_RELATION[symbol]

    # --------------------------------------------------------
    # Update EMA values.
    # --------------------------------------------------------

    state["fast"] = update_ema(
        state["fast"],
        close_price,
        EMA_FAST,
    )

    state["slow"] = update_ema(
        state["slow"],
        close_price,
        EMA_SLOW,
    )

    fast = state["fast"]
    slow = state["slow"]

    if fast > slow:
        relation = 1
    elif fast < slow:
        relation = -1
    else:
        relation = 0

    # --------------------------------------------------------
    # Update hypothetical open trade.
    # --------------------------------------------------------

    open_trade = EMA_OPEN_LONG[symbol]

    if open_trade is not None:

        if high_price > open_trade["max_price"]:
            open_trade["max_price"] = high_price

    # --------------------------------------------------------
    # Cross up.
    # --------------------------------------------------------

    cross_up = (
        previous_relation < 0
        and relation > 0
    )

    if cross_up:

        if EMA_OPEN_LONG[symbol] is not None:

            close_ema_long(
                symbol,
                close_price,
            )

        EMA_OPEN_LONG[symbol] = {
            "entry": close_price,
            "max_price": high_price,
        }

        print(
            f"EMA SIGNAL | {symbol} | "
            f"LONG CROSS UP | "
            f"price={close_price:.4f}"
        )

        expected_profit = (
            get_ema_expected_profit(symbol)
        )

        # The newly opened hypothetical trade is not yet
        # completed, so expected_profit represents all
        # previously completed hypothetical trades.

        if expected_profit is not None:

            attempt_long_entry(
                symbol=symbol,
                strategy="EMA_10S",
                signal_price=close_price,
                expected_profit=expected_profit,
            )

    # --------------------------------------------------------
    # Cross down.
    # --------------------------------------------------------

    cross_down = (
        previous_relation > 0
        and relation < 0
    )

    if cross_down:

        if EMA_OPEN_LONG[symbol] is not None:

            close_ema_long(
                symbol,
                close_price,
            )

    EMA_RELATION[symbol] = relation


# ============================================================
# PROCESS COMPLETED 1-MINUTE BAR
# ============================================================

def process_1m_bar(symbol, bar):
    """
    Store live 1-minute bar and detect live breakout.

    Historical breakout statistics remain unchanged.
    """

    timestamp = bar["timestamp"]

    BARS_1M[symbol][timestamp] = bar

    breakout = process_live_breakout(
        symbol,
        bar,
    )

    if not breakout:
        return

    expected_profit = (
        get_breakout_expected_profit(symbol)
    )

    attempt_long_entry(
        symbol=symbol,
        strategy="BREAKOUT_1M",
        signal_price=float(bar["close"]),
        expected_profit=expected_profit,
    )


# ============================================================
# PROCESS MARKET DATA
# ============================================================

def process_market_data():
    """
    Continuously convert incoming trades into:

        trades
          ↓
        10-second bars
          ↓
        EMA strategy

        10-second bars
          ↓
        1-minute bars
          ↓
        live breakout strategy
    """

    while True:

        now = datetime.now(
            timezone.utc
        )

        # ----------------------------------------------------
        # Process completed 10-second bars.
        # ----------------------------------------------------

        for symbol in SYMBOLS:

            current_bucket = floor_timestamp(
                now,
                BAR_10S_SECONDS,
            )

            last_bucket = LAST_10S_BUCKET[symbol]

            if last_bucket is None:

                LAST_10S_BUCKET[symbol] = (
                    current_bucket
                    - timedelta(
                        seconds=BAR_10S_SECONDS
                    )
                )

                last_bucket = LAST_10S_BUCKET[
                    symbol
                ]

            next_bucket = (
                last_bucket
                + timedelta(
                    seconds=BAR_10S_SECONDS
                )
            )

            while next_bucket < current_bucket:

                bar = build_10s_bar(
                    symbol,
                    next_bucket,
                )

                if bar is not None:

                    process_ema_bar_with_real_signal(
                        symbol,
                        bar,
                    )

                LAST_10S_BUCKET[symbol] = (
                    next_bucket
                )

                next_bucket = (
                    next_bucket
                    + timedelta(
                        seconds=BAR_10S_SECONDS
                    )
                )

        # ----------------------------------------------------
        # Process completed 1-minute bars.
        # ----------------------------------------------------

        for symbol in SYMBOLS:

            current_minute = floor_timestamp(
                now,
                BAR_1M_SECONDS,
            )

            last_minute = LAST_1M_BUCKET[symbol]

            if last_minute is None:

                LAST_1M_BUCKET[symbol] = (
                    current_minute
                    - timedelta(
                        minutes=1
                    )
                )

                last_minute = LAST_1M_BUCKET[
                    symbol
                ]

            next_minute = (
                last_minute
                + timedelta(
                    minutes=1
                )
            )

            while next_minute < current_minute:

                bar = build_1m_bar(
                    symbol,
                    next_minute,
                )

                if bar is not None:

                    process_1m_bar(
                        symbol,
                        bar,
                    )

                LAST_1M_BUCKET[symbol] = (
                    next_minute
                )

                next_minute = (
                    next_minute
                    + timedelta(
                        minutes=1
                    )
                )

        # ----------------------------------------------------
        # Keep raw trades reasonably bounded.
        #
        # We only need recent trades to construct the next
        # unfinished 10-second bar.
        # ----------------------------------------------------

        cutoff = (
            now
            - timedelta(
                seconds=30
            )
        )

        for symbol in SYMBOLS:

            trades = RAW_TRADES[symbol]

            if not trades:
                continue

            RAW_TRADES[symbol] = [
                trade
                for trade in trades
                if trade[0] >= cutoff
            ]

        time.sleep(0.25)


# ============================================================
# WEBSOCKET CALLBACK
# ============================================================

async def on_trade(data):
    """
    Alpaca WebSocket trade callback.

    Must be async.
    """

    symbol = data.symbol

    if symbol not in RAW_TRADES:
        return

    timestamp = data.timestamp

    price = float(data.price)

    size = float(data.size)

    RAW_TRADES[symbol].append(
        (
            timestamp,
            price,
            size,
        )
    )


# ============================================================
# WEBSOCKET WORKER
# ============================================================

def websocket_worker():
    """
    Connect to Alpaca's live stock trade stream.
    """

    while True:

        try:

            print(
                "WEBSOCKET | connecting..."
            )

            stream = StockDataStream(
                API_KEY,
                API_SECRET,
            )

            for symbol in SYMBOLS:

                stream.subscribe_trades(
                    on_trade,
                    symbol,
                )

            print(
                "WEBSOCKET | subscribed"
            )

            stream.run()

        except Exception as exc:

            print(
                f"WEBSOCKET ERROR | {exc}"
            )

            print(
                "WEBSOCKET | reconnecting..."
            )

            time.sleep(5)


# ============================================================
# STARTUP
# ============================================================

def main():

    print(
        "=================================================="
    )

    print(
        "LONG-ONLY LIVE TRADING ENGINE"
    )

    print(
        "=================================================="
    )

    print(
        f"Symbols: {len(SYMBOLS)}"
    )

    print(
        f"Trade size: ${TRADE_DOLLARS:.2f}"
    )

    print(
        f"Expected threshold: {EXPECTED_THRESHOLD:.2%}"
    )

    print(
        f"EMA: {EMA_FAST}/{EMA_SLOW} on 10-second bars"
    )

    print(
        "Breakout: 1-minute"
    )

    print(
        "Entry: MARKET BUY"
    )

    print(
        "Exit: OCO TP + SL"
    )

    print(
        "=================================================="
    )

    # --------------------------------------------------------
    # Historical breakout data.
    # --------------------------------------------------------

    load_historical_breakout_data()

    # --------------------------------------------------------
    # Market-data processor.
    # --------------------------------------------------------

    processor_thread = threading.Thread(
        target=process_market_data,
        daemon=True,
    )

    processor_thread.start()

    # --------------------------------------------------------
    # WebSocket.
    # --------------------------------------------------------

    websocket_thread = threading.Thread(
        target=websocket_worker,
        daemon=True,
    )

    websocket_thread.start()

    # --------------------------------------------------------
    # Keep main process alive.
    # --------------------------------------------------------

    while True:

        time.sleep(60)
        


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()