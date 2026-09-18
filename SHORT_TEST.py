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
API_SECRET = "4nj9w53MrNKJGZsHqN7Siqy34z2Gis9TffWi2beszNU"

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

EXPECTED_THRESHOLD = 0.00

ORDER_UPDATE_SECONDS = 30

EXIT_CHECK_SECONDS = 2

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
# LIVE STATE
# ============================================================

CURRENT_1M_BAR = {
    symbol: None
    for symbol in SYMBOLS
}

CURRENT_MINUTE = {
    symbol: None
    for symbol in SYMBOLS
}


# True means this stock already entered during
# the current 1-minute bar.
TRADED_THIS_BAR = {
    symbol: False
    for symbol in SYMBOLS
}


# Historical expected-profit statistics.
BREAKOUT_STATS = {
    symbol: {
        "sum": 0.0,
        "count": 0,
    }
    for symbol in SYMBOLS
}


# Current pending BUY STOP order.
ENTRY_ORDER_IDS = {
    symbol: None
    for symbol in SYMBOLS
}


# Last entry trigger submitted for each stock.
LAST_ENTRY_PRICE = {
    symbol: None
    for symbol in SYMBOLS
}


# OCO parent orders for historical/current trades.
OCO_ORDER_IDS = {
    symbol: []
    for symbol in SYMBOLS
}


# Entry orders whose fills have already been processed.
PROCESSED_ENTRY_FILLS = set()


# OCO orders whose exit fill has already been reported.
PROCESSED_EXIT_FILLS = set()


REAL_TRADE_COUNT = 0


STATE_LOCK = threading.Lock()


# ============================================================
# HISTORICAL BREAKOUT STATISTICS
# ============================================================

def calculate_historical_breakout_stats(
    symbol,
    bars,
):
    """
    Historical breakout:

        current bar high > previous bar high

    Reference price:

        previous bar high

    Future window:

        breakout bar + next 3 bars

    Expected profit:

        (future_max_high - previous_high)
        / previous_high
    """

    if bars is None:
        return

    if len(bars) < BREAKOUT_FUTURE_BARS + 2:
        return

    highs = np.asarray(
        bars["high"],
        dtype=np.float64,
    )

    total = 0.0
    count = 0

    future_window = BREAKOUT_FUTURE_BARS + 1

    max_index = len(highs) - future_window

    for i in range(
        1,
        max_index + 1,
    ):

        previous_high = highs[i - 1]

        breakout_high = highs[i]

        if previous_high <= 0:
            continue

        if breakout_high <= previous_high:
            continue

        future_max_high = np.max(
            highs[
                i:i + future_window
            ]
        )

        profit = (
            future_max_high
            - previous_high
        ) / previous_high

        total += profit

        count += 1

    BREAKOUT_STATS[symbol] = {
        "sum": total,
        "count": count,
    }


def get_expected_profit(symbol):

    stats = BREAKOUT_STATS[symbol]

    if stats["count"] == 0:
        return None

    return (
        stats["sum"]
        / stats["count"]
    )


# ============================================================
# HISTORICAL DATA
# ============================================================

def load_historical_stats(symbol):

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

        response = (
            historical_client
            .get_stock_bars(request)
        )

        bars = response.df

        if bars is None or len(bars) == 0:

            print(
                f"[HIST] {symbol}: "
                f"no historical data"
            )

            return

        calculate_historical_breakout_stats(
            symbol,
            bars,
        )

        expected = get_expected_profit(
            symbol
        )

        if expected is None:

            print(
                f"[HIST] {symbol}: "
                f"no breakout samples"
            )

        else:

            print(
                f"[HIST] {symbol}: "
                f"breakouts="
                f"{BREAKOUT_STATS[symbol]['count']} "
                f"expected="
                f"{expected:.2%}"
            )

    except Exception as e:

        print(
            f"[HIST ERROR] "
            f"{symbol}: {e}"
        )


def load_all_historical_stats():

    print()
    print("========================================")
    print("LOADING HISTORICAL DATA")
    print("========================================")

    for symbol in SYMBOLS:

        load_historical_stats(
            symbol
        )

    print()
    print("Historical calculation complete.")
    print()


# ============================================================
# LIVE 1-MINUTE BAR
# ============================================================

def get_minute_timestamp(timestamp):

    return timestamp.replace(
        second=0,
        microsecond=0,
    )


def create_new_bar(
    symbol,
    timestamp,
    price,
    size,
):

    minute = get_minute_timestamp(
        timestamp
    )

    CURRENT_1M_BAR[symbol] = {
        "timestamp": minute,
        "open": price,
        "high": price,
        "low": price,
        "close": price,
        "volume": size,
    }

    CURRENT_MINUTE[symbol] = minute

    TRADED_THIS_BAR[symbol] = False

    LAST_ENTRY_PRICE[symbol] = None

    print(
        f"[BAR] {symbol} "
        f"{minute} "
        f"new 1m bar"
    )


def update_live_1m_bar(data):

    symbol = data.symbol

    if symbol not in CURRENT_1M_BAR:
        return

    timestamp = data.timestamp

    price = float(
        data.price
    )

    size = float(
        data.size
    )

    minute = get_minute_timestamp(
        timestamp
    )

    current_bar = CURRENT_1M_BAR[symbol]

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
# PRICE ROUNDING
# ============================================================

def round_price(price):

    price = float(price)

    if price >= 1.0:
        return round(price, 2)

    return round(price, 4)


# ============================================================
# GET NORMAL ORDER
# ============================================================

def get_order(order_id):

    if order_id is None:
        return None

    try:

        return trading_client.get_order_by_id(
            order_id
        )

    except Exception as e:

        print(
            f"[ORDER GET ERROR] "
            f"{order_id}: {e}"
        )

        return None


# ============================================================
# GET NESTED ORDER
# ============================================================

def get_nested_order(
    order_id,
    symbol=None,
):
    """
    Retrieves an order with nested multi-leg orders.

    alpaca-py does not accept nested=True on
    get_order_by_id() in the installed SDK.

    Therefore we use get_orders() with nested=True
    and locate the requested order.
    """

    if order_id is None:
        return None

    try:

        request = GetOrdersRequest(
            status=QueryOrderStatus.ALL,
            limit=500,
            nested=True,
        )

        if symbol is not None:

            request = GetOrdersRequest(
                status=QueryOrderStatus.ALL,
                limit=500,
                nested=True,
                symbols=[symbol],
            )

        orders = trading_client.get_orders(
            filter=request
        )

        wanted_id = str(
            order_id
        )

        for order in orders:

            if str(order.id) == wanted_id:
                return order

            legs = getattr(
                order,
                "legs",
                None,
            )

            if not legs:
                continue

            for leg in legs:

                if str(leg.id) == wanted_id:
                    return order

        return None

    except Exception as e:

        print(
            f"[NESTED ORDER GET ERROR] "
            f"{order_id}: {e}"
        )

        return None


# ============================================================
# ENTRY ORDER CANCELLATION
# ============================================================

def cancel_existing_entry(
    symbol,
):

    order_id = ENTRY_ORDER_IDS[symbol]

    if order_id is None:
        return False

    order = get_order(
        order_id
    )

    if order is None:

        ENTRY_ORDER_IDS[symbol] = None
        LAST_ENTRY_PRICE[symbol] = None

        return False

    status = str(
        order.status
    ).lower()

    if status == "filled":

        process_entry_fill(
            symbol,
            order,
        )

        return True

    if status in {
        "canceled",
        "cancelled",
        "rejected",
        "expired",
    }:

        ENTRY_ORDER_IDS[symbol] = None
        LAST_ENTRY_PRICE[symbol] = None

        return False

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

    time.sleep(0.15)

    order_after = get_order(
        order_id
    )

    if order_after is None:

        ENTRY_ORDER_IDS[symbol] = None
        LAST_ENTRY_PRICE[symbol] = None

        return False

    final_status = str(
        order_after.status
    ).lower()

    if final_status == "filled":

        process_entry_fill(
            symbol,
            order_after,
        )

        return True

    if final_status in {
        "canceled",
        "cancelled",
        "rejected",
        "expired",
    }:

        ENTRY_ORDER_IDS[symbol] = None
        LAST_ENTRY_PRICE[symbol] = None

        return False

    return False


# ============================================================
# EXIT PRICE CALCULATION
# ============================================================

def calculate_exit_prices(
    entry_price,
    expected_profit,
):

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


# ============================================================
# SUBMIT OCO
# ============================================================

def submit_oco_after_fill(
    symbol,
    qty,
    entry_price,
):

    expected_profit = get_expected_profit(
        symbol
    )

    if expected_profit is None:

        print(
            f"[OCO ERROR] {symbol}: "
            f"no historical expected profit"
        )

        return None

    take_profit, stop_loss = (
        calculate_exit_prices(
            entry_price,
            expected_profit,
        )
    )

    if take_profit is None:

        print(
            f"[OCO ERROR] {symbol}: "
            f"invalid TP/SL"
        )

        return None

    print(
        f"[OCO SUBMIT] {symbol} "
        f"entry={entry_price:.4f} "
        f"expected={expected_profit:.2%} "
        f"TP={take_profit:.4f} "
        f"SL={stop_loss:.4f} "
        f"qty={qty}"
    )

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

        order_id = str(
            order.id
        )

        OCO_ORDER_IDS[symbol].append(
            order_id
        )

        print(
            f"[OCO ACCEPTED] "
            f"{symbol} "
            f"order={order_id}"
        )

        verify_oco(
            symbol,
            order_id,
        )

        return order_id

    except Exception as e:

        print(
            f"[OCO ERROR] "
            f"{symbol}: {e}"
        )

        return None


# ============================================================
# VERIFY OCO
# ============================================================

def verify_oco(
    symbol,
    order_id,
):

    order = get_nested_order(
        order_id,
        symbol=symbol,
    )

    if order is None:

        print(
            f"[OCO VERIFY ERROR] "
            f"{symbol} "
            f"order={order_id}"
        )

        return

    print(
        f"[OCO VERIFY] "
        f"{symbol} "
        f"parent_status="
        f"{order.status}"
    )

    legs = getattr(
        order,
        "legs",
        None,
    )

    if not legs:

        print(
            f"[OCO VERIFY] "
            f"{symbol} "
            f"no legs returned"
        )

        return

    for leg in legs:

        print(
            f"[OCO LEG] "
            f"{symbol} "
            f"id={leg.id} "
            f"side={leg.side} "
            f"type={leg.type} "
            f"status={leg.status} "
            f"limit={getattr(leg, 'limit_price', None)} "
            f"stop={getattr(leg, 'stop_price', None)}"
        )


# ============================================================
# PROCESS ENTRY FILL
# ============================================================

def process_entry_fill(
    symbol,
    order,
):

    global REAL_TRADE_COUNT

    order_id = str(
        order.id
    )

    if order_id in PROCESSED_ENTRY_FILLS:

        ENTRY_ORDER_IDS[symbol] = None

        return

    PROCESSED_ENTRY_FILLS.add(
        order_id
    )

    if order.filled_avg_price is None:
        print(
            f"[ENTRY FILL ERROR] "
            f"{symbol}: no filled price"
        )
        return

    filled_price = float(
        order.filled_avg_price
    )

    filled_qty = float(
        order.filled_qty
    )

    REAL_TRADE_COUNT += 1

    TRADED_THIS_BAR[symbol] = True

    ENTRY_ORDER_IDS[symbol] = None

    LAST_ENTRY_PRICE[symbol] = None

    print(
        f"[ENTRY FILLED] "
        f"{symbol} "
        f"qty={filled_qty} "
        f"price={filled_price:.4f} "
        f"trade_count={REAL_TRADE_COUNT}"
    )

    submit_oco_after_fill(
        symbol,
        filled_qty,
        filled_price,
    )


# ============================================================
# CHECK ENTRY ORDER
# ============================================================

def check_entry_order(
    symbol,
):

    order_id = ENTRY_ORDER_IDS[symbol]

    if order_id is None:
        return False

    order = get_order(
        order_id
    )

    if order is None:
        return False

    status = str(
        order.status
    ).lower()

    if status == "filled":

        process_entry_fill(
            symbol,
            order,
        )

        return True

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
        LAST_ENTRY_PRICE[symbol] = None

        return False

    return False


# ============================================================
# CURRENT MARKET PRICE
# ============================================================

def get_current_market_price(
    symbol,
):

    bar = CURRENT_1M_BAR[symbol]

    if bar is None:
        return None

    return float(
        bar["close"]
    )


# ============================================================
# SUBMIT ENTRY
# ============================================================

def submit_entry_order(
    symbol,
    entry_price,
):

    entry_price = round_price(
        entry_price
    )

    if entry_price <= 0:
        return

    current_price = (
        get_current_market_price(
            symbol
        )
    )

    if current_price is None:
        return

    if entry_price <= current_price:

        print(
            f"[ENTRY SKIP] "
            f"{symbol} "
            f"trigger={entry_price:.4f} "
            f"market={current_price:.4f} "
            f"trigger_not_above_market"
        )

        return

    qty = math.floor(
        TRADE_DOLLARS
        / entry_price
    )

    if qty < 1:

        print(
            f"[ENTRY SKIP] "
            f"{symbol}: "
            f"price={entry_price:.4f}"
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

        LAST_ENTRY_PRICE[symbol] = (
            entry_price
        )

        print(
            f"[ENTRY] "
            f"{symbol} "
            f"BUY STOP "
            f"qty={qty} "
            f"trigger={entry_price:.4f} "
            f"market={current_price:.4f} "
            f"order={order.id}"
        )

    except Exception as e:

        # Alpaca can reject the stop if the market
        # moved through the trigger between our local
        # validation and server-side order validation.

        ENTRY_ORDER_IDS[symbol] = None
        LAST_ENTRY_PRICE[symbol] = None

        print(
            f"[ENTRY ERROR] "
            f"{symbol}: {e}"
        )


# ============================================================
# UPDATE ONE ENTRY
# ============================================================

def update_entry_order(
    symbol,
):

    bar = CURRENT_1M_BAR[symbol]

    if bar is None:
        return

    # --------------------------------------------------------
    # Already traded this bar.
    # --------------------------------------------------------

    if TRADED_THIS_BAR[symbol]:

        if ENTRY_ORDER_IDS[symbol] is not None:

            check_entry_order(
                symbol
            )

            if (
                ENTRY_ORDER_IDS[symbol]
                is not None
            ):

                cancel_existing_entry(
                    symbol
                )

        return

    # --------------------------------------------------------
    # Historical expected-profit filter.
    # --------------------------------------------------------

    expected_profit = (
        get_expected_profit(
            symbol
        )
    )

    if (
        expected_profit is None
        or expected_profit <= EXPECTED_THRESHOLD
    ):

        if ENTRY_ORDER_IDS[symbol] is not None:

            cancel_existing_entry(
                symbol
            )

        return

    # --------------------------------------------------------
    # Check existing order.
    # --------------------------------------------------------

    if ENTRY_ORDER_IDS[symbol] is not None:

        filled = check_entry_order(
            symbol
        )

        if filled:
            return

    # --------------------------------------------------------
    # Calculate trigger from current 1-minute high.
    # --------------------------------------------------------

    current_high = float(
        bar["high"]
    )

    entry_price = round_price(
        current_high
        + ENTRY_OFFSET
    )

    # --------------------------------------------------------
    # Get newest locally known market price.
    # --------------------------------------------------------

    current_price = (
        get_current_market_price(
            symbol
        )
    )

    if current_price is None:
        return

    # --------------------------------------------------------
    # Trigger must still be above market.
    # --------------------------------------------------------

    if entry_price <= current_price:

        if ENTRY_ORDER_IDS[symbol] is not None:

            cancel_existing_entry(
                symbol
            )

        print(
            f"[ENTRY WAIT] "
            f"{symbol} "
            f"trigger={entry_price:.4f} "
            f"market={current_price:.4f}"
        )

        return

    # --------------------------------------------------------
    # Existing order already has this trigger.
    # --------------------------------------------------------

    if (
        ENTRY_ORDER_IDS[symbol]
        is not None
        and LAST_ENTRY_PRICE[symbol]
        == entry_price
    ):

        return

    # --------------------------------------------------------
    # Replace old order.
    # --------------------------------------------------------

    if ENTRY_ORDER_IDS[symbol] is not None:

        filled_during_cancel = (
            cancel_existing_entry(
                symbol
            )
        )

        if filled_during_cancel:
            return

    # --------------------------------------------------------
    # Check trade state again.
    # --------------------------------------------------------

    if TRADED_THIS_BAR[symbol]:
        return

    # --------------------------------------------------------
    # Final market-price check.
    # --------------------------------------------------------

    current_price = (
        get_current_market_price(
            symbol
        )
    )

    if current_price is None:
        return

    if entry_price <= current_price:

        print(
            f"[ENTRY SKIP] "
            f"{symbol} "
            f"trigger={entry_price:.4f} "
            f"market={current_price:.4f}"
        )

        return

    # --------------------------------------------------------
    # Submit.
    # --------------------------------------------------------

    submit_entry_order(
        symbol,
        entry_price,
    )


# ============================================================
# UPDATE ALL ENTRIES
# ============================================================

def update_all_entry_orders():

    while True:

        start = time.time()

        for symbol in SYMBOLS:

            try:

                with STATE_LOCK:

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
            - start
        )

        time.sleep(
            max(
                0.1,
                ORDER_UPDATE_SECONDS
                - elapsed,
            )
        )


# ============================================================
# EXIT MONITOR
# ============================================================

def monitor_oco(
    symbol,
    oco_id,
):
    """
    Monitor one OCO order and its legs.

    Alpaca executes the exits.

    This function only observes/report fills.
    """

    order = get_nested_order(
        oco_id,
        symbol=symbol,
    )

    if order is None:
        return

    legs = getattr(
        order,
        "legs",
        None,
    )

    if not legs:
        return

    for leg in legs:

        leg_id = str(
            leg.id
        )

        status = str(
            leg.status
        ).lower()

        # ----------------------------------------------------
        # EXIT FILLED
        # ----------------------------------------------------

        if status == "filled":

            if leg_id in PROCESSED_EXIT_FILLS:
                continue

            PROCESSED_EXIT_FILLS.add(
                leg_id
            )

            filled_price = getattr(
                leg,
                "filled_avg_price",
                None,
            )

            limit_price = getattr(
                leg,
                "limit_price",
                None,
            )

            stop_price = getattr(
                leg,
                "stop_price",
                None,
            )

            leg_type = str(
                leg.type
            ).lower()

            if (
                limit_price is not None
                and leg_type == "limit"
            ):

                exit_type = "TAKE_PROFIT"

            elif stop_price is not None:

                exit_type = "STOP_LOSS"

            else:

                exit_type = "EXIT"

            print()
            print(
                "========================================"
            )
            print(
                f"[EXIT FILLED] {symbol}"
            )
            print(
                f"type={exit_type}"
            )
            print(
                f"order={leg_id}"
            )
            print(
                f"filled_price={filled_price}"
            )
            print(
                f"limit_price={limit_price}"
            )
            print(
                f"stop_price={stop_price}"
            )
            print(
                "========================================"
            )
            print()

        # ----------------------------------------------------
        # PRINT REJECTION
        # ----------------------------------------------------

        elif status in {
            "rejected",
            "expired",
        }:

            print(
                f"[EXIT ERROR] "
                f"{symbol} "
                f"leg={leg_id} "
                f"status={status}"
            )


def monitor_all_oco_orders():

    while True:

        for symbol in SYMBOLS:

            try:

                with STATE_LOCK:

                    order_ids = list(
                        OCO_ORDER_IDS[symbol]
                    )

                for oco_id in order_ids:

                    monitor_oco(
                        symbol,
                        oco_id,
                    )

            except Exception as e:

                print(
                    f"[EXIT MONITOR ERROR] "
                    f"{symbol}: {e}"
                )

        time.sleep(
            EXIT_CHECK_SECONDS
        )


# ============================================================
# WEBSOCKET
# ============================================================

async def on_trade(data):

    symbol = data.symbol

    if symbol not in CURRENT_1M_BAR:
        return

    with STATE_LOCK:

        update_live_1m_bar(
            data
        )


def websocket_worker():

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
# MAIN
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
        f"Entry refresh: "
        f"{ORDER_UPDATE_SECONDS}s"
    )

    print(
        f"Exit monitoring: "
        f"{EXIT_CHECK_SECONDS}s"
    )

    print(
        "Long only"
    )

    print(
        "1 trade per stock per 1-minute bar"
    )

    print(
        "Multiple trades across different bars allowed"
    )

    print()

    # --------------------------------------------------------
    # HISTORICAL
    # --------------------------------------------------------

    load_all_historical_stats()

    # --------------------------------------------------------
    # WEBSOCKET
    # --------------------------------------------------------

    websocket_thread = threading.Thread(
        target=websocket_worker,
        daemon=True,
    )

    websocket_thread.start()

    # --------------------------------------------------------
    # ENTRY ORDER UPDATER
    # --------------------------------------------------------

    entry_thread = threading.Thread(
        target=update_all_entry_orders,
        daemon=True,
    )

    entry_thread.start()

    # --------------------------------------------------------
    # EXIT MONITOR
    # --------------------------------------------------------

    exit_thread = threading.Thread(
        target=monitor_all_oco_orders,
        daemon=True,
    )

    exit_thread.start()

    # --------------------------------------------------------
    # KEEP ALIVE
    # --------------------------------------------------------

    while True:

        time.sleep(60)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()