

import os
import time
import math
import threading
from datetime import datetime, timedelta, timezone

import numpy as np

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.live import StockDataStream
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    StopOrderRequest,
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
    "HPE",
    "AMD",
    "AAPL",
    "NVDA",
    "DELL",
    "INTC",
    "CRWD",
]

TRADE_DOLLARS = 100.00

EXPECTED_THRESHOLD = 0.02

ORDER_UPDATE_SECONDS = 30

ENTRY_OFFSET = 0.01

BREAKOUT_FUTURE_BARS = 3

TP_FRACTION = 0.50

SL_FRACTION_OF_TP = 0.50

HIST_START = datetime(
    2026,
    1,
    1,
    tzinfo=timezone.utc,
)


# ============================================================
# ALPACA CLIENTS
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
# LIVE STATE
# ============================================================

# Current live 1-minute bar for each stock.
CURRENT_1M_BAR = {
    symbol: None
    for symbol in SYMBOLS
}


# Current minute identifier for each stock.
CURRENT_MINUTE = {
    symbol: None
    for symbol in SYMBOLS
}


# One-trade-per-bar state.
#
# False:
#     Stock is allowed to enter a trade in this 1-minute bar.
#
# True:
#     Stock already entered a trade during this 1-minute bar.
#
# This resets when a new 1-minute bar starts.
TRADED_THIS_BAR = {
    symbol: False
    for symbol in SYMBOLS
}


# Historical expected-profit statistics.
#
# {
#     symbol: {
#         "sum": ...,
#         "count": ...
#     }
# }
BREAKOUT_STATS = {
    symbol: {
        "sum": 0.0,
        "count": 0,
    }
    for symbol in SYMBOLS
}


# Currently active pending BUY STOP order for each stock.
ENTRY_ORDER_IDS = {
    symbol: None
    for symbol in SYMBOLS
}


# Entry orders that have already been processed as fills.
PROCESSED_ENTRY_FILLS = set()


# Number of completed real trades.
REAL_TRADE_COUNT = 0


# Protect shared state between WebSocket and order thread.
STATE_LOCK = threading.Lock()


# ============================================================
# HISTORICAL BREAKOUT CALCULATION
# ============================================================

def calculate_historical_breakout_stats(symbol, bars):
    """
    Calculate historical expected maximum profit.

    Breakout definition:

        current_high > previous_high

    Reference entry:

        previous_high

    Future window:

        breakout bar + next 3 bars

    Maximum future price:

        max(highs[i : i + 4])

    Profit:

        (future_max_high - previous_high) / previous_high

    Only sum and count are stored.
    """

    if bars is None or len(bars) < BREAKOUT_FUTURE_BARS + 2:
        return

    highs = np.asarray(
        bars["high"],
        dtype=np.float64,
    )

    total = 0.0
    count = 0

    future_window = BREAKOUT_FUTURE_BARS + 1

    max_index = len(highs) - future_window

    for i in range(1, max_index + 1):

        previous_high = highs[i - 1]
        breakout_high = highs[i]

        if previous_high <= 0:
            continue

        if breakout_high <= previous_high:
            continue

        future_max_high = np.max(
            highs[i:i + future_window]
        )

        profit = (
            future_max_high - previous_high
        ) / previous_high

        total += profit
        count += 1

    BREAKOUT_STATS[symbol] = {
        "sum": total,
        "count": count,
    }


def get_expected_profit(symbol):
    """
    Return historical average expected profit.
    """

    stats = BREAKOUT_STATS[symbol]

    if stats["count"] <= 0:
        return None

    return stats["sum"] / stats["count"]


# ============================================================
# HISTORICAL DATA LOADING
# ============================================================

def load_historical_stats(symbol):
    """
    Download historical 1-minute bars and calculate
    fixed expected-profit statistics.

    These statistics do not change during the session.
    """

    end = (
        datetime.now(timezone.utc)
        - timedelta(minutes=10)
    )

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Minute,
        start=HIST_START,
        end=end,
        feed=DataFeed.IEX,
    )

    try:

        bars_response = historical_client.get_stock_bars(
            request
        )

        bars = bars_response.df

        if bars is None or len(bars) == 0:
            print(
                f"[HIST] {symbol}: no historical data"
            )
            return

        calculate_historical_breakout_stats(
            symbol,
            bars,
        )

        expected = get_expected_profit(symbol)

        if expected is None:

            print(
                f"[HIST] {symbol}: "
                f"no breakout samples"
            )

        else:

            print(
                f"[HIST] {symbol}: "
                f"breakouts={BREAKOUT_STATS[symbol]['count']} "
                f"expected={expected:.2%}"
            )

    except Exception as e:

        print(
            f"[HIST ERROR] {symbol}: {e}"
        )


def load_all_historical_stats():
    """
    Load all historical statistics once.
    """

    print()
    print("========================================")
    print("LOADING HISTORICAL DATA")
    print("========================================")

    for symbol in SYMBOLS:

        load_historical_stats(symbol)

    print()
    print("Historical calculation complete.")
    print()


# ============================================================
# LIVE 1-MINUTE BAR
# ============================================================

def get_minute_timestamp(timestamp):
    """
    Convert trade timestamp into its 1-minute bucket.
    """

    return timestamp.replace(
        second=0,
        microsecond=0,
    )


def create_new_bar(symbol, timestamp, price, size):
    """
    Start a new live 1-minute bar.
    """

    minute = get_minute_timestamp(timestamp)

    CURRENT_1M_BAR[symbol] = {
        "timestamp": minute,
        "open": price,
        "high": price,
        "low": price,
        "close": price,
        "volume": size,
    }

    CURRENT_MINUTE[symbol] = minute

    # IMPORTANT:
    #
    # A new minute means the stock can trade again.
    #
    TRADED_THIS_BAR[symbol] = False

    print(
        f"[BAR] {symbol} "
        f"{minute} "
        f"new 1m bar"
    )


def update_live_1m_bar(data):
    """
    Update the current 1-minute bar directly from
    incoming Alpaca trade data.

    No software-side breakout detection occurs here.
    """

    symbol = data.symbol

    if symbol not in CURRENT_1M_BAR:
        return

    timestamp = data.timestamp

    price = float(data.price)

    size = float(data.size)

    minute = get_minute_timestamp(timestamp)

    current_bar = CURRENT_1M_BAR[symbol]

    # --------------------------------------------------------
    # NEW 1-MINUTE BAR
    # --------------------------------------------------------

    if (
        current_bar is None
        or CURRENT_MINUTE[symbol] != minute
    ):

        create_new_bar(
            symbol,
            timestamp,
            price,
            size,
        )

        return

    # --------------------------------------------------------
    # SAME 1-MINUTE BAR
    # --------------------------------------------------------

    current_bar["high"] = max(
        current_bar["high"],
        price,
    )

    current_bar["low"] = min(
        current_bar["low"],
        price,
    )

    current_bar["close"] = price

    current_bar["volume"] += size


# ============================================================
# ORDER HELPERS
# ============================================================

def round_price(price):
    """
    Alpaca-compatible price precision.
    """

    price = float(price)

    if price >= 1.0:
        return round(price, 2)

    return round(price, 4)


def get_order(order_id):
    """
    Retrieve an Alpaca order.
    """

    if order_id is None:
        return None

    try:

        return trading_client.get_order_by_id(
            order_id
        )

    except Exception as e:

        print(
            f"[ORDER ERROR] "
            f"get_order_by_id {order_id}: {e}"
        )

        return None


def cancel_existing_entry(symbol):
    """
    Cancel the currently stored pending entry order.
    """

    order_id = ENTRY_ORDER_IDS[symbol]

    if order_id is None:
        return

    try:

        trading_client.cancel_order_by_id(
            order_id
        )

        print(
            f"[ENTRY CANCEL] "
            f"{symbol} "
            f"{order_id}"
        )

    except Exception as e:

        print(
            f"[CANCEL ERROR] "
            f"{symbol}: {e}"
        )

    ENTRY_ORDER_IDS[symbol] = None


# ============================================================
# OCO EXIT
# ============================================================

def calculate_exit_prices(entry_price, expected_profit):
    """
    Calculate TP and SL.

    Expected profit = X

    TP = 50% of X

    SL = 50% of TP
    """

    tp_percent = (
        expected_profit
        * TP_FRACTION
    )

    sl_percent = (
        tp_percent
        * SL_FRACTION_OF_TP
    )

    take_profit = (
        entry_price
        * (1.0 + tp_percent)
    )

    stop_loss = (
        entry_price
        * (1.0 - sl_percent)
    )

    take_profit = round_price(
        take_profit
    )

    stop_loss = round_price(
        stop_loss
    )

    if stop_loss <= 0:
        return None, None

    if stop_loss >= take_profit:
        return None, None

    return (
        take_profit,
        stop_loss,
    )


def submit_oco_after_fill(
    symbol,
    qty,
    entry_price,
):
    """
    Submit the OCO exit after the BUY fills.
    """

    expected_profit = get_expected_profit(
        symbol
    )

    if expected_profit is None:
        print(
            f"[OCO SKIP] {symbol}: "
            f"no expected profit"
        )
        return

    take_profit, stop_loss = (
        calculate_exit_prices(
            entry_price,
            expected_profit,
        )
    )

    if take_profit is None:
        print(
            f"[OCO SKIP] {symbol}: "
            f"invalid TP/SL"
        )
        return

    try:

        request = LimitOrderRequest(
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

        order = trading_client.submit_order(
            order_data=request
        )

        print(
            f"[OCO] {symbol} "
            f"qty={qty} "
            f"entry={entry_price:.4f} "
            f"TP={take_profit:.4f} "
            f"SL={stop_loss:.4f} "
            f"order={order.id}"
        )

    except Exception as e:

        print(
            f"[OCO ERROR] {symbol}: {e}"
        )


# ============================================================
# ENTRY FILL PROCESSING
# ============================================================

def check_entry_order(symbol):
    """
    Check whether the current BUY STOP has filled.

    Returns:

        True  = the entry order filled
        False = it did not fill
    """

    global REAL_TRADE_COUNT

    order_id = ENTRY_ORDER_IDS[symbol]

    if order_id is None:
        return False

    order = get_order(order_id)

    if order is None:
        return False

    status = str(
        order.status
    ).lower()

    # --------------------------------------------------------
    # FILLED
    # --------------------------------------------------------

    if status == "filled":

        fill_key = str(order.id)

        if fill_key in PROCESSED_ENTRY_FILLS:

            ENTRY_ORDER_IDS[symbol] = None

            return True

        PROCESSED_ENTRY_FILLS.add(
            fill_key
        )

        filled_price = float(
            order.filled_avg_price
        )

        filled_qty = float(
            order.filled_qty
        )

        REAL_TRADE_COUNT += 1

        # This is the important per-bar rule.
        #
        # We have entered a trade during this
        # 1-minute bar, so no additional entry
        # is allowed until the next bar.
        TRADED_THIS_BAR[symbol] = True

        print(
            f"[ENTRY FILLED] "
            f"{symbol} "
            f"qty={filled_qty} "
            f"price={filled_price:.4f} "
            f"trade_count={REAL_TRADE_COUNT}"
        )

        # Remove the pending entry order from state.
        ENTRY_ORDER_IDS[symbol] = None

        # Alpaca now handles the exit through OCO.
        submit_oco_after_fill(
            symbol,
            filled_qty,
            filled_price,
        )

        return True

    # --------------------------------------------------------
    # DEAD ORDER
    # --------------------------------------------------------

    if status in {
        "canceled",
        "cancelled",
        "rejected",
        "expired",
    }:

        print(
            f"[ENTRY DEAD] "
            f"{symbol} "
            f"status={status}"
        )

        ENTRY_ORDER_IDS[symbol] = None

        return False

    return False


# ============================================================
# CREATE ENTRY ORDER
# ============================================================

def submit_entry_order(
    symbol,
    entry_price,
):
    """
    Submit a BUY STOP order.

    Alpaca watches the market and triggers the
    entry when its stop condition is reached.
    """

    entry_price = round_price(
        entry_price
    )

    if entry_price <= 0:
        return

    qty = math.floor(
        TRADE_DOLLARS / entry_price
    )

    # Cannot buy even one whole share.
    if qty < 1:

        print(
            f"[ENTRY SKIP] {symbol}: "
            f"price={entry_price:.4f} "
            f"requires > ${TRADE_DOLLARS:.2f}"
        )

        return

    try:

        request = StopOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.GTC,
            stop_price=entry_price,
        )

        order = trading_client.submit_order(
            order_data=request
        )

        ENTRY_ORDER_IDS[symbol] = (
            str(order.id)
        )

        print(
            f"[ENTRY] {symbol} "
            f"BUY STOP "
            f"qty={qty} "
            f"trigger={entry_price:.4f} "
            f"order={order.id}"
        )

    except Exception as e:

        print(
            f"[ENTRY ERROR] "
            f"{symbol}: {e}"
        )


# ============================================================
# UPDATE ONE STOCK'S ENTRY
# ============================================================

def update_entry_order(symbol):
    """
    Maintain the pending BUY STOP for one stock.

    The Python program does NOT detect the breakout.

    It simply tells Alpaca:

        "If price reaches this level, buy."

    The order is refreshed every 30 seconds using
    the current 1-minute bar high.
    """

    # --------------------------------------------------------
    # Must have a live bar.
    # --------------------------------------------------------

    current_bar = CURRENT_1M_BAR[symbol]

    if current_bar is None:
        return

    # --------------------------------------------------------
    # If this stock already traded during this bar,
    # absolutely no second entry is allowed.
    # --------------------------------------------------------

    if TRADED_THIS_BAR[symbol]:

        # Make sure there isn't an old pending order.
        if ENTRY_ORDER_IDS[symbol] is not None:

            cancel_existing_entry(symbol)

        return

    # --------------------------------------------------------
    # Historical expected-profit filter.
    # --------------------------------------------------------

    expected_profit = get_expected_profit(
        symbol
    )

    if (
        expected_profit is None
        or expected_profit <= EXPECTED_THRESHOLD
    ):

        cancel_existing_entry(symbol)

        return

    # --------------------------------------------------------
    # Check whether existing entry filled.
    # --------------------------------------------------------

    if ENTRY_ORDER_IDS[symbol] is not None:

        filled = check_entry_order(
            symbol
        )

        if filled:
            return

    # --------------------------------------------------------
    # If the stock traded during this bar while
    # check_entry_order() was running, stop here.
    # --------------------------------------------------------

    if TRADED_THIS_BAR[symbol]:
        return

    # --------------------------------------------------------
    # Current 1-minute high.
    #
    # Entry = high + $0.01
    # --------------------------------------------------------

    current_high = float(
        current_bar["high"]
    )

    entry_price = (
        current_high
        + ENTRY_OFFSET
    )

    entry_price = round_price(
        entry_price
    )

    # --------------------------------------------------------
    # Whole-share sizing.
    # --------------------------------------------------------

    qty = math.floor(
        TRADE_DOLLARS / entry_price
    )

    if qty < 1:

        cancel_existing_entry(symbol)

        return

    # --------------------------------------------------------
    # Remove old order.
    # --------------------------------------------------------

    cancel_existing_entry(symbol)

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # The old order may have filled right before
    # cancellation completed.
    #
    # Check once more before creating a new one.
    # --------------------------------------------------------

    if TRADED_THIS_BAR[symbol]:
        return

    # --------------------------------------------------------
    # Submit new BUY STOP.
    # --------------------------------------------------------

    submit_entry_order(
        symbol,
        entry_price,
    )


# ============================================================
# UPDATE ALL ENTRY ORDERS
# ============================================================

def update_all_entry_orders():
    """
    Refresh all pending BUY STOP orders every 30 seconds.
    """

    while True:

        start_time = time.time()

        for symbol in SYMBOLS:

            try:

                update_entry_order(
                    symbol
                )

            except Exception as e:

                print(
                    f"[UPDATE ERROR] "
                    f"{symbol}: {e}"
                )

        elapsed = (
            time.time()
            - start_time
        )

        sleep_time = max(
            0.1,
            ORDER_UPDATE_SECONDS
            - elapsed,
        )

        time.sleep(
            sleep_time
        )


# ============================================================
# LIVE WEBSOCKET
# ============================================================

async def on_trade(data):
    """
    Alpaca trade callback.

    Every trade directly updates the current
    1-minute bar.
    """

    symbol = data.symbol

    if symbol not in CURRENT_1M_BAR:
        return

    with STATE_LOCK:

        update_live_1m_bar(
            data
        )


def websocket_worker():
    """
    One Alpaca WebSocket for all stocks.
    """

    while True:

        try:

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
                "[WS] Starting live stream..."
            )

            stream.run()

        except Exception as e:

            print(
                f"[WS ERROR] {e}"
            )

            print(
                "[WS] Reconnecting in 5 seconds..."
            )

            time.sleep(5)


# ============================================================
# STARTUP
# ============================================================

def main():

    print()
    print("========================================")
    print("LIVE TRADING ENGINE")
    print("========================================")
    print()
    print(
        f"Symbols: {len(SYMBOLS)}"
    )
    print(
        f"Trade size: ${TRADE_DOLLARS:.2f}"
    )
    print(
        f"Expected threshold: "
        f"{EXPECTED_THRESHOLD:.2%}"
    )
    print(
        f"Entry offset: "
        f"${ENTRY_OFFSET:.2f}"
    )
    print(
        f"Order refresh: "
        f"{ORDER_UPDATE_SECONDS}s"
    )
    print(
        "Max entries: 1 per stock per 1-minute bar"
    )
    print()

    # --------------------------------------------------------
    # Historical expected-profit calculation
    # --------------------------------------------------------

    load_all_historical_stats()

    # --------------------------------------------------------
    # Start live WebSocket
    # --------------------------------------------------------

    websocket_thread = threading.Thread(
        target=websocket_worker,
        daemon=True,
    )

    websocket_thread.start()

    # --------------------------------------------------------
    # Start Alpaca order updater
    # --------------------------------------------------------

    order_thread = threading.Thread(
        target=update_all_entry_orders,
        daemon=True,
    )

    order_thread.start()

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