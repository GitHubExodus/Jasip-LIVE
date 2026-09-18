



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

EXPECTED_THRESHOLD = 0.02

# Update each stock's entry order every 30 seconds.
ORDER_UPDATE_SECONDS = 30

# Entry is one cent above the current 1-minute high.
ENTRY_OFFSET = 0.01

# Historical breakout:
# previous bar high -> breakout bar + next 3 bars
BREAKOUT_FUTURE_BARS = 3

# TP = half expected historical max profit.
TP_FRACTION = 0.50

# SL = half of TP percentage.
SL_FRACTION_OF_TP = 0.50

HIST_START = datetime(
    2026,
    1,
    1,
    tzinfo=timezone.utc,
)


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
# LIVE TRADE DATA
# ============================================================

# symbol -> current 1-minute bar
CURRENT_1M_BAR = {
    symbol: None
    for symbol in SYMBOLS
}


# ============================================================
# HISTORICAL BREAKOUT STATS
# ============================================================

# Only sum and count are stored.
BREAKOUT_STATS = {
    symbol: {
        "sum": 0.0,
        "count": 0,
    }
    for symbol in SYMBOLS
}


# ============================================================
# ENTRY ORDER STATE
# ============================================================

# symbol -> Alpaca entry order ID
ENTRY_ORDER_IDS = {
    symbol: None
    for symbol in SYMBOLS
}

ENTRY_ORDER_LOCK = threading.Lock()


# ============================================================
# OCO STATE
# ============================================================

# Entry order IDs for which an OCO has already been submitted.
OCO_SUBMITTED = set()

OCO_LOCK = threading.Lock()


# ============================================================
# REAL TRADE COUNT
# ============================================================

REAL_TRADE_COUNT = 0

REAL_TRADE_COUNT_LOCK = threading.Lock()


# ============================================================
# CURRENT LIVE MINUTE
# ============================================================

CURRENT_MINUTE = {
    symbol: None
    for symbol in SYMBOLS
}


# ============================================================
# TIME HELPERS
# ============================================================

def floor_minute(timestamp):
    return timestamp.replace(
        second=0,
        microsecond=0,
    )


# ============================================================
# PRICE ROUNDING
# ============================================================

def round_stop_price(price):
    """
    Alpaca allows:
        >= $1.00 -> 2 decimals
        <  $1.00 -> 4 decimals
    """

    if price >= 1.00:
        return round(price, 2)

    return round(price, 4)


def round_limit_price(price):
    """
    Equity limit prices are normally submitted to cents
    for these stocks.
    """

    if price >= 1.00:
        return round(price, 2)

    return round(price, 4)


# ============================================================
# POSITION SIZE
# ============================================================

def calculate_quantity(price):
    """
    Maximum $100 position.
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
# HISTORICAL BREAKOUT STATISTICS
# ============================================================

def calculate_historical_breakout_stats(
    symbol,
    bars,
):
    """
    Historical LONG breakout calculation.

    Breakout:
        current high > previous high

    Entry/reference:
        previous bar high

    Maximum future high:
        breakout bar + next 3 bars

    Profit:
        (future max high - previous high)
        / previous high

    Only sum/count are stored.
    """

    highs = np.asarray(
        [
            float(bar.high)
            for bar in bars
        ],
        dtype=np.float64,
    )

    n = len(highs)

    total_sum = 0.0
    total_count = 0

    # Need:
    #
    # i - 1 = previous bar
    # i     = breakout
    # i+1
    # i+2
    # i+3
    #
    # Therefore i must stop at n - 4.

    for i in range(
        1,
        n - BREAKOUT_FUTURE_BARS,
    ):

        previous_high = highs[i - 1]

        breakout_high = highs[i]

        if breakout_high <= previous_high:
            continue

        future_end = (
            i
            + BREAKOUT_FUTURE_BARS
            + 1
        )

        max_future_high = np.max(
            highs[i:future_end]
        )

        if previous_high <= 0:
            continue

        profit = (
            max_future_high
            - previous_high
        ) / previous_high

        total_sum += profit
        total_count += 1

    BREAKOUT_STATS[symbol]["sum"] = (
        total_sum
    )

    BREAKOUT_STATS[symbol]["count"] = (
        total_count
    )

    if total_count > 0:

        average = (
            total_sum
            / total_count
        )

        print(
            f"HIST BREAKOUT | {symbol} | "
            f"n={total_count} | "
            f"avg={average:.2%}"
        )

    else:

        print(
            f"HIST BREAKOUT | {symbol} | "
            f"n=0 | avg=N/A"
        )


def get_expected_profit(symbol):
    stats = BREAKOUT_STATS[symbol]

    if stats["count"] == 0:
        return None

    return (
        stats["sum"]
        / stats["count"]
    )


# ============================================================
# HISTORICAL DATA LOADING
# ============================================================

def load_historical_breakout_data():
    """
    Download historical 1-minute data once.

    IEX is explicitly requested because the current account
    may not have permission for recent SIP historical data.
    """

    end = (
        datetime.now(timezone.utc)
        - timedelta(minutes=10)
    )

    print(
        "Loading historical 1-minute data..."
    )

    for symbol in SYMBOLS:

        try:

            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Minute,
                start=HIST_START,
                end=end,
                feed=DataFeed.IEX,
            )

            response = (
                historical_client
                .get_stock_bars(request)
            )

            bars = response[symbol]

            calculate_historical_breakout_stats(
                symbol,
                bars,
            )

        except Exception as exc:

            print(
                f"HIST ERROR | "
                f"{symbol} | {exc}"
            )

    print(
        "Historical data loaded."
    )


# ============================================================
# LIVE 1-MINUTE BAR
# ============================================================

def update_live_1m_bar(data):
    """
    Update the current 1-minute bar directly from trades.

    No 10-second bars are created.
    """

    symbol = data.symbol

    timestamp = data.timestamp

    price = float(data.price)

    size = float(data.size)

    minute = floor_minute(timestamp)

    current = CURRENT_1M_BAR[symbol]

    # --------------------------------------------------------
    # New minute.
    # --------------------------------------------------------

    if (
        current is None
        or current["timestamp"] != minute
    ):

        current = {
            "timestamp": minute,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": size,
        }

        CURRENT_1M_BAR[symbol] = current

        CURRENT_MINUTE[symbol] = minute

        return

    # --------------------------------------------------------
    # Existing minute.
    # --------------------------------------------------------

    if price > current["high"]:
        current["high"] = price

    if price < current["low"]:
        current["low"] = price

    current["close"] = price

    current["volume"] += size


# ============================================================
# ALPACA EXPOSURE
# ============================================================

def get_position(symbol):
    try:

        return trading_client.get_open_position(
            symbol
        )

    except Exception:

        return None


def has_position(symbol):
    position = get_position(symbol)

    if position is None:
        return False

    try:
        return float(position.qty) > 0
    except Exception:
        return False


# ============================================================
# CANCEL EXISTING ENTRY ORDER
# ============================================================

def cancel_existing_entry(symbol):
    """
    Cancel the current pending BUY STOP for this symbol.
    """

    with ENTRY_ORDER_LOCK:

        order_id = ENTRY_ORDER_IDS[symbol]

        if order_id is None:
            return

        try:

            trading_client.cancel_order_by_id(
                order_id
            )

            print(
                f"ENTRY CANCEL | {symbol} | "
                f"order={order_id}"
            )

        except Exception as exc:

            print(
                f"ENTRY CANCEL ERROR | "
                f"{symbol} | {exc}"
            )

        ENTRY_ORDER_IDS[symbol] = None


# ============================================================
# FIND OPEN ENTRY ORDER
# ============================================================

def has_open_entry_order(symbol):
    """
    Check whether Alpaca still has an open entry order.
    """

    try:

        request = GetOrdersRequest(
            status=QueryOrderStatus.OPEN,
        )

        orders = trading_client.get_orders(
            filter=request
        )

        for order in orders:

            if (
                order.symbol == symbol
                and order.side == OrderSide.BUY
            ):
                return True

        return False

    except Exception as exc:

        print(
            f"OPEN ORDER CHECK ERROR | "
            f"{symbol} | {exc}"
        )

        # Fail safe.
        return True


# ============================================================
# CALCULATE EXIT PRICES
# ============================================================

def calculate_exit_prices(
    entry_price,
    expected_profit,
):
    """
    Expected historical profit:
        X%

    TP:
        X * 50%

    SL:
        TP * 50%

    Example:

        expected = 4%

        TP = 2%
        SL = 1%
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

    take_profit = round_limit_price(
        take_profit
    )

    stop_loss = round_stop_price(
        stop_loss
    )

    # Make sure stop is below TP.
    if stop_loss >= take_profit:

        stop_loss = round_stop_price(
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
# SUBMIT OCO AFTER ENTRY FILL
# ============================================================

def submit_oco_after_fill(
    symbol,
    entry_order_id,
    filled_qty,
    filled_price,
    expected_profit,
):
    """
    Once the BUY STOP has actually filled, submit the
    Alpaca OCO exit.

    OCO:
        SELL LIMIT TP
        SELL STOP SL

    Alpaca cancels the other exit when one executes.
    """

    with OCO_LOCK:

        if entry_order_id in OCO_SUBMITTED:
            return

        (
            take_profit,
            stop_loss,
            tp_percent,
            sl_percent,
        ) = calculate_exit_prices(
            filled_price,
            expected_profit,
        )

        try:

            request = LimitOrderRequest(
                symbol=symbol,
                qty=filled_qty,
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

            order = (
                trading_client.submit_order(
                    order_data=request
                )
            )

            OCO_SUBMITTED.add(
                entry_order_id
            )

            print(
                f"OCO SUBMITTED | {symbol} | "
                f"qty={filled_qty} | "
                f"entry={filled_price:.4f} | "
                f"TP={take_profit:.4f} "
                f"(+{tp_percent:.2%}) | "
                f"SL={stop_loss:.4f} "
                f"(-{sl_percent:.2%}) | "
                f"order={order.id}"
            )

        except Exception as exc:

            print(
                f"OCO FAILED | {symbol} | "
                f"entry={filled_price:.4f} | "
                f"TP={take_profit:.4f} | "
                f"SL={stop_loss:.4f} | "
                f"{exc}"
            )


# ============================================================
# CHECK ENTRY ORDER FILLS
# ============================================================

def check_entry_order(symbol):
    """
    Check the currently stored BUY STOP order.

    If Alpaca filled it:
        submit OCO exits.
    """

    with ENTRY_ORDER_LOCK:
        order_id = ENTRY_ORDER_IDS[symbol]

    if order_id is None:
        return

    try:

        order = (
            trading_client
            .get_order_by_id(order_id)
        )

    except Exception as exc:

        print(
            f"ENTRY STATUS ERROR | "
            f"{symbol} | {exc}"
        )

        return

    status = str(
        order.status
    ).lower()

    # --------------------------------------------------------
    # Filled.
    # --------------------------------------------------------

    if status == "filled":

        filled_price = float(
            order.filled_avg_price
        )

        filled_qty = int(
            float(order.filled_qty)
        )

        expected_profit = (
            get_expected_profit(symbol)
        )

        print(
            f"ENTRY FILLED | {symbol} | "
            f"qty={filled_qty} | "
            f"price={filled_price:.4f}"
        )

        if expected_profit is not None:

            submit_oco_after_fill(
                symbol=symbol,
                entry_order_id=str(
                    order.id
                ),
                filled_qty=filled_qty,
                filled_price=filled_price,
                expected_profit=expected_profit,
            )

        with ENTRY_ORDER_LOCK:
            ENTRY_ORDER_IDS[symbol] = None

        return

    # --------------------------------------------------------
    # Terminal failure/cancellation.
    # --------------------------------------------------------

    if status in {
        "canceled",
        "cancelled",
        "rejected",
        "expired",
    }:

        print(
            f"ENTRY CLOSED | {symbol} | "
            f"status={status} | "
            f"order={order.id}"
        )

        with ENTRY_ORDER_LOCK:
            ENTRY_ORDER_IDS[symbol] = None


# ============================================================
# CREATE / REPLACE BUY STOP
# ============================================================

def update_entry_order(symbol):
    """
    Called every 30 seconds.

    Current logic:

        current 1-minute high
                +
              $0.01
                ↓
        BUY STOP

    The previous BUY STOP for the stock is removed first.

    If the stock already has a position, no new entry order
    is placed.
    """

    current_bar = CURRENT_1M_BAR[symbol]

    if current_bar is None:
        return

    expected_profit = (
        get_expected_profit(symbol)
    )

    if expected_profit is None:

        print(
            f"SKIP ENTRY | {symbol} | "
            f"no historical breakout data"
        )

        return

    if expected_profit <= EXPECTED_THRESHOLD:

        print(
            f"SKIP ENTRY | {symbol} | "
            f"expected={expected_profit:.2%} "
            f"<= {EXPECTED_THRESHOLD:.2%}"
        )

        cancel_existing_entry(symbol)

        return

    # --------------------------------------------------------
    # If already holding the stock, there should be no
    # breakout entry order.
    # --------------------------------------------------------

    if has_position(symbol):

        cancel_existing_entry(symbol)

        print(
            f"NO ENTRY | {symbol} | "
            f"position already open"
        )

        return

    # --------------------------------------------------------
    # Check whether existing order has filled.
    # --------------------------------------------------------

    check_entry_order(symbol)

    if has_position(symbol):

        cancel_existing_entry(symbol)

        return

    # --------------------------------------------------------
    # New entry level.
    #
    # Current 1-minute high + $0.01.
    # --------------------------------------------------------

    current_high = float(
        current_bar["high"]
    )

    entry_price = (
        current_high
        + ENTRY_OFFSET
    )

    entry_price = round_stop_price(
        entry_price
    )

    qty = calculate_quantity(
        entry_price
    )

    if qty <= 0:

        print(
            f"SKIP ENTRY | {symbol} | "
            f"price={entry_price:.4f} | "
            f"too expensive for ${TRADE_DOLLARS}"
        )

        cancel_existing_entry(symbol)

        return

    # --------------------------------------------------------
    # Remove old order.
    # --------------------------------------------------------

    cancel_existing_entry(symbol)

    # --------------------------------------------------------
    # Submit new BUY STOP.
    # --------------------------------------------------------

    try:

        request = StopOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.GTC,
            stop_price=entry_price,
        )

        order = (
            trading_client.submit_order(
                order_data=request
            )
        )

        order_id = str(order.id)

        with ENTRY_ORDER_LOCK:
            ENTRY_ORDER_IDS[symbol] = order_id

        print(
            f"ENTRY UPDATED | {symbol} | "
            f"BUY STOP | "
            f"qty={qty} | "
            f"trigger={entry_price:.4f} | "
            f"current_high={current_high:.4f} | "
            f"expected={expected_profit:.2%} | "
            f"order={order_id}"
        )

    except Exception as exc:

        print(
            f"ENTRY ORDER FAILED | "
            f"{symbol} | "
            f"trigger={entry_price:.4f} | "
            f"{exc}"
        )


# ============================================================
# UPDATE ALL ENTRY ORDERS
# ============================================================

def update_all_entry_orders():
    """
    Every 30 seconds:

        1. Check whether existing entries filled.
        2. Remove old pending entry.
        3. Create new BUY STOP based on current
           1-minute high.
    """

    global REAL_TRADE_COUNT

    while True:

        for symbol in SYMBOLS:

            try:

                before = ENTRY_ORDER_IDS[symbol]

                check_entry_order(symbol)

                after = ENTRY_ORDER_IDS[symbol]

                # If it filled, count the actual trade.
                if (
                    before is not None
                    and after is None
                    and has_position(symbol)
                ):

                    with REAL_TRADE_COUNT_LOCK:

                        REAL_TRADE_COUNT += 1

                        print(
                            f"REAL TRADE COUNT | "
                            f"{REAL_TRADE_COUNT}"
                        )

                update_entry_order(
                    symbol
                )

            except Exception as exc:

                print(
                    f"UPDATE ERROR | "
                    f"{symbol} | {exc}"
                )

        time.sleep(
            ORDER_UPDATE_SECONDS
        )


# ============================================================
# WEBSOCKET TRADE CALLBACK
# ============================================================

async def on_trade(data):
    """
    Every incoming trade directly updates the current
    1-minute bar.

    There are no 10-second bars.
    """

    if data.symbol not in CURRENT_1M_BAR:
        return

    update_live_1m_bar(
        data
    )


# ============================================================
# WEBSOCKET WORKER
# ============================================================

def websocket_worker():

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
                f"WEBSOCKET | subscribed "
                f"{len(SYMBOLS)} symbols"
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
# MAIN
# ============================================================

def main():

    print(
        "=================================================="
    )

    print(
        "1-MINUTE BREAKOUT ORDER ENGINE"
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
        "Entry: BUY STOP"
    )

    print(
        "Exit: OCO TP + SL"
    )

    print(
        "=================================================="
    )

    # --------------------------------------------------------
    # 1. Historical expected-profit calculation.
    # --------------------------------------------------------

    load_historical_breakout_data()

    # --------------------------------------------------------
    # 2. Start WebSocket.
    # --------------------------------------------------------

    websocket_thread = threading.Thread(
        target=websocket_worker,
        daemon=True,
    )

    websocket_thread.start()

    # --------------------------------------------------------
    # 3. Start order updater.
    # --------------------------------------------------------

    order_thread = threading.Thread(
        target=update_all_entry_orders,
        daemon=True,
    )

    order_thread.start()

    # --------------------------------------------------------
    # 4. Keep application alive.
    # --------------------------------------------------------

    while True:

        time.sleep(60)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()