
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
    MarketOrderRequest,
)
from alpaca.trading.enums import (
    OrderSide,
    TimeInForce,
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


# Dollar amount used for each entry.
TRADE_DOLLARS = 100.00


# ============================================================
# ENTRY
# ============================================================

# Historical expected-profit filter.
#
# Set to 0.00 to allow every symbol with at least
# one historical breakout.
EXPECTED_THRESHOLD = 0.01


# Entry trigger is:
#
# previous/current breakout high + ENTRY_OFFSET
#
# Example:
#
# breakout high = 5.18
# offset = 0.01
# trigger = 5.19
#
# Once a live tick crosses 5.19, we BUY at market.
ENTRY_OFFSET = 0.01


# ============================================================
# EXIT
# ============================================================

# Take profit:
#
# +1.00%
#
# When Alpaca reports unrealized_plpc >= this value,
# submit a market SELL.
TP_PERCENT = 0.01


# Stop loss:
#
# -0.50%
#
# When Alpaca reports unrealized_plpc <= this value,
# submit a market SELL.
SL_PERCENT = -0.005


# How frequently to ask Alpaca for current positions.
POSITION_CHECK_SECONDS = 1.0


# How long to wait after submitting an entry before
# checking the order status again.
ENTRY_ORDER_CHECK_SECONDS = 0.25


# ============================================================
# HISTORICAL BREAKOUT
# ============================================================

BREAKOUT_FUTURE_BARS = 3

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


# True once this symbol has entered during
# the current 1-minute bar.
TRADED_THIS_BAR = {
    symbol: False
    for symbol in SYMBOLS
}


# ============================================================
# ENTRY STATE
# ============================================================

# Current market-entry order ID.
#
# Market orders can take a short amount of time to fill.
ENTRY_ORDER_IDS = {
    symbol: None
    for symbol in SYMBOLS
}


# Prevents multiple entry submissions while an
# entry order is still being processed.
ENTRY_PENDING = {
    symbol: False
    for symbol in SYMBOLS
}


# ============================================================
# POSITION STATE
# ============================================================

# True when we believe this program has an open trade.
POSITION_OPEN = {
    symbol: False
    for symbol in SYMBOLS
}


# Prevents submitting multiple SELL orders while
# an exit is already being processed.
EXIT_PENDING = {
    symbol: False
    for symbol in SYMBOLS
}


# Last Alpaca-reported P&L percentage.
LAST_PNL = {
    symbol: None
    for symbol in SYMBOLS
}


# ============================================================
# HISTORICAL STATISTICS
# ============================================================

BREAKOUT_STATS = {
    symbol: {
        "sum": 0.0,
        "count": 0,
    }
    for symbol in SYMBOLS
}


# ============================================================
# ACCOUNT STATE
# ============================================================

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

    Reference:

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

    future_window = (
        BREAKOUT_FUTURE_BARS + 1
    )

    max_index = (
        len(highs)
        - future_window
    )

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

        if (
            bars is None
            or len(bars) == 0
        ):

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
    print(
        "Historical calculation complete."
    )
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

    # New minute means the symbol can
    # potentially enter again.
    TRADED_THIS_BAR[symbol] = False

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

    # --------------------------------------------------------
    # NEW MINUTE
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
    # SAME MINUTE
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
# CURRENT PRICE
# ============================================================

def get_current_market_price(symbol):

    bar = CURRENT_1M_BAR[symbol]

    if bar is None:
        return None

    return float(
        bar["close"]
    )


# ============================================================
# ENTRY TRIGGER
# ============================================================

def get_entry_trigger(symbol):

    bar = CURRENT_1M_BAR[symbol]

    if bar is None:
        return None

    current_high = float(
        bar["high"]
    )

    return (
        current_high
        + ENTRY_OFFSET
    )


# ============================================================
# CHECK ALPACA POSITION
# ============================================================

def get_alpaca_position(symbol):

    try:

        position = (
            trading_client
            .get_open_position(symbol)
        )

        return position

    except Exception:

        # A 404/no-position situation is normal
        # when there is no open position.

        return None


# ============================================================
# CHECK ALL POSITIONS
# ============================================================

def refresh_position_state():

    try:

        positions = (
            trading_client
            .get_all_positions()
        )

    except Exception as e:

        print(
            f"[POSITION ERROR] {e}"
        )

        return

    position_map = {
        position.symbol: position
        for position in positions
    }

    with STATE_LOCK:

        for symbol in SYMBOLS:

            position = position_map.get(
                symbol
            )

            if position is None:

                # No open position.
                #
                # Do NOT immediately clear EXIT_PENDING
                # if a sell order was just submitted.
                #
                # The next cycle will naturally confirm
                # the position is gone.

                if not ENTRY_PENDING[symbol]:

                    POSITION_OPEN[symbol] = False

                LAST_PNL[symbol] = None

                continue

            # ------------------------------------------------
            # Position exists
            # ------------------------------------------------

            POSITION_OPEN[symbol] = True

            try:

                pnl_percent = float(
                    position.unrealized_plpc
                )

            except Exception:

                pnl_percent = None

            LAST_PNL[symbol] = (
                pnl_percent
            )


# ============================================================
# SUBMIT MARKET ENTRY
# ============================================================

def submit_market_entry(
    symbol,
):

    # --------------------------------------------------------
    # Do not enter if already holding.
    # --------------------------------------------------------

    if POSITION_OPEN[symbol]:
        return

    # --------------------------------------------------------
    # Do not submit another entry while one
    # is already pending.
    # --------------------------------------------------------

    if ENTRY_PENDING[symbol]:
        return

    price = get_current_market_price(
        symbol
    )

    if price is None:
        return

    qty = math.floor(
        TRADE_DOLLARS / price
    )

    if qty < 1:

        print(
            f"[ENTRY SKIP] {symbol}: "
            f"price={price:.4f}"
        )

        return

    ENTRY_PENDING[symbol] = True

    try:

        request = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )

        order = (
            trading_client
            .submit_order(
                order_data=request
            )
        )

        order_id = str(
            order.id
        )

        ENTRY_ORDER_IDS[symbol] = (
            order_id
        )

        print(
            f"[ENTRY] {symbol} "
            f"BUY MARKET "
            f"qty={qty} "
            f"market={price:.4f} "
            f"order={order_id}"
        )

    except Exception as e:

        ENTRY_PENDING[symbol] = False
        ENTRY_ORDER_IDS[symbol] = None

        print(
            f"[ENTRY ERROR] "
            f"{symbol}: {e}"
        )

        return


# ============================================================
# VERIFY ENTRY
# ============================================================

def check_entry_fill(symbol):

    if not ENTRY_PENDING[symbol]:
        return

    order_id = (
        ENTRY_ORDER_IDS[symbol]
    )

    if order_id is None:
        return

    try:

        order = (
            trading_client
            .get_order_by_id(
                order_id
            )
        )

    except Exception as e:

        print(
            f"[ENTRY ORDER ERROR] "
            f"{symbol}: {e}"
        )

        return

    status = str(
        order.status
    ).lower()

    # --------------------------------------------------------
    # FILLED
    # --------------------------------------------------------

    if status == "filled":

        ENTRY_PENDING[symbol] = False
        POSITION_OPEN[symbol] = True

        filled_price = (
            order.filled_avg_price
        )

        filled_qty = (
            order.filled_qty
        )

        print(
            f"[ENTRY FILLED] "
            f"{symbol} "
            f"qty={filled_qty} "
            f"price={filled_price}"
        )

        return

    # --------------------------------------------------------
    # DEAD
    # --------------------------------------------------------

    if status in {
        "canceled",
        "cancelled",
        "rejected",
        "expired",
    }:

        ENTRY_PENDING[symbol] = False
        ENTRY_ORDER_IDS[symbol] = None

        print(
            f"[ENTRY DEAD] "
            f"{symbol} "
            f"status={status}"
        )


# ============================================================
# ENTRY CROSSING LOGIC
# ============================================================

def check_entry_crossing(
    symbol,
):

    # --------------------------------------------------------
    # Already traded this bar.
    # --------------------------------------------------------

    if TRADED_THIS_BAR[symbol]:
        return

    # --------------------------------------------------------
    # Already have position.
    # --------------------------------------------------------

    if POSITION_OPEN[symbol]:
        return

    # --------------------------------------------------------
    # Entry order still being filled.
    # --------------------------------------------------------

    if ENTRY_PENDING[symbol]:
        return

    # --------------------------------------------------------
    # Historical filter.
    # --------------------------------------------------------

    expected_profit = (
        get_expected_profit(symbol)
    )

    if (
        expected_profit is None
        or expected_profit <= EXPECTED_THRESHOLD
    ):
        return

    # --------------------------------------------------------
    # Get current trigger.
    #
    # NOTE:
    #
    # The trigger is based on the current 1-minute
    # high + offset.
    #
    # Since we watch every tick, the entry happens
    # when the live tick actually reaches/crosses it.
    # --------------------------------------------------------

    trigger = get_entry_trigger(
        symbol
    )

    if trigger is None:
        return

    current_price = (
        get_current_market_price(
            symbol
        )
    )

    if current_price is None:
        return

    # --------------------------------------------------------
    # CROSS ABOVE TRIGGER
    # --------------------------------------------------------

    if current_price >= trigger:

        print(
            f"[BREAKOUT] {symbol} "
            f"price={current_price:.4f} "
            f"trigger={trigger:.4f}"
        )

        TRADED_THIS_BAR[symbol] = True

        submit_market_entry(
            symbol
        )


# ============================================================
# EXIT ONE POSITION
# ============================================================

def submit_market_exit(
    symbol,
    position,
    reason,
    pnl_percent,
):

    if EXIT_PENDING[symbol]:
        return

    EXIT_PENDING[symbol] = True

    try:

        qty = float(
            position.qty
        )

        if qty <= 0:

            EXIT_PENDING[symbol] = False

            return

        request = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )

        order = (
            trading_client
            .submit_order(
                order_data=request
            )
        )

        print(
            f"[EXIT] {symbol} "
            f"SELL MARKET "
            f"qty={qty} "
            f"reason={reason} "
            f"pnl={pnl_percent:.2%} "
            f"order={order.id}"
        )

    except Exception as e:

        EXIT_PENDING[symbol] = False

        print(
            f"[EXIT ERROR] "
            f"{symbol}: {e}"
        )


# ============================================================
# CHECK ONE POSITION PNL
# ============================================================

def check_position_exit(
    symbol,
    position,
):

    if position is None:
        return

    if EXIT_PENDING[symbol]:
        return

    try:

        pnl_percent = float(
            position.unrealized_plpc
        )

    except Exception as e:

        print(
            f"[PNL ERROR] "
            f"{symbol}: {e}"
        )

        return

    LAST_PNL[symbol] = (
        pnl_percent
    )

    # --------------------------------------------------------
    # TAKE PROFIT
    # --------------------------------------------------------

    if pnl_percent >= TP_PERCENT:

        submit_market_exit(
            symbol,
            position,
            "TAKE_PROFIT",
            pnl_percent,
        )

        return

    # --------------------------------------------------------
    # STOP LOSS
    # --------------------------------------------------------

    if pnl_percent <= SL_PERCENT:

        submit_market_exit(
            symbol,
            position,
            "STOP_LOSS",
            pnl_percent,
        )

        return


# ============================================================
# POSITION MONITOR
# ============================================================

def position_monitor():

    while True:

        try:

            # ------------------------------------------------
            # First check whether pending entry orders
            # filled.
            # ------------------------------------------------

            for symbol in SYMBOLS:

                if ENTRY_PENDING[symbol]:

                    try:

                        check_entry_fill(
                            symbol
                        )

                    except Exception as e:

                        print(
                            f"[ENTRY CHECK ERROR] "
                            f"{symbol}: {e}"
                        )

            # ------------------------------------------------
            # Get current positions from Alpaca.
            # ------------------------------------------------

            try:

                positions = (
                    trading_client
                    .get_all_positions()
                )

            except Exception as e:

                print(
                    f"[POSITION GET ERROR] "
                    f"{e}"
                )

                time.sleep(
                    POSITION_CHECK_SECONDS
                )

                continue

            position_map = {
                position.symbol: position
                for position in positions
            }

            # ------------------------------------------------
            # Check every symbol.
            # ------------------------------------------------

            for symbol in SYMBOLS:

                position = position_map.get(
                    symbol
                )

                # ------------------------------------------------
                # No position
                # ------------------------------------------------

                if position is None:

                    if (
                        EXIT_PENDING[symbol]
                    ):

                        # The position disappeared,
                        # meaning the sell has completed.
                        EXIT_PENDING[symbol] = False

                        POSITION_OPEN[symbol] = False

                        print(
                            f"[EXIT CONFIRMED] "
                            f"{symbol}"
                        )

                    elif not ENTRY_PENDING[symbol]:

                        POSITION_OPEN[symbol] = False

                    LAST_PNL[symbol] = None

                    continue

                # ------------------------------------------------
                # Position exists
                # ------------------------------------------------

                POSITION_OPEN[symbol] = True

                # ------------------------------------------------
                # Check P&L against TP / SL.
                # ------------------------------------------------

                check_position_exit(
                    symbol,
                    position,
                )

            time.sleep(
                POSITION_CHECK_SECONDS
            )

        except Exception as e:

            print(
                f"[POSITION MONITOR ERROR] "
                f"{e}"
            )

            time.sleep(
                POSITION_CHECK_SECONDS
            )


# ============================================================
# ENTRY MONITOR
# ============================================================

def entry_monitor():

    while True:

        start = time.time()

        for symbol in SYMBOLS:

            try:

                with STATE_LOCK:

                    check_entry_crossing(
                        symbol
                    )

            except Exception as e:

                print(
                    f"[ENTRY MONITOR ERROR] "
                    f"{symbol}: {e}"
                )

        elapsed = (
            time.time()
            - start
        )

        # This loop is intentionally very fast.
        #
        # The actual market-price updates come from
        # the websocket.
        #
        # We only need to inspect the latest local
        # price here.

        time.sleep(
            max(
                0.01,
                0.05 - elapsed,
            )
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

        # ----------------------------------------------------
        # ENTRY IS CHECKED DIRECTLY ON EVERY TICK.
        #
        # This is important.
        #
        # We don't wait for the 1-minute bar to close.
        # ----------------------------------------------------

        check_entry_crossing(
            symbol
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
# PRINT POSITION STATUS
# ============================================================

def status_monitor():

    last_status_time = 0

    while True:

        now = time.time()

        if (
            now - last_status_time
            >= 5
        ):

            last_status_time = now

            try:

                positions = (
                    trading_client
                    .get_all_positions()
                )

                for position in positions:

                    symbol = position.symbol

                    try:

                        pnl = float(
                            position.unrealized_plpc
                        )

                    except Exception:

                        pnl = None

                    try:

                        qty = float(
                            position.qty
                        )

                    except Exception:

                        qty = position.qty

                    if pnl is not None:

                        print(
                            f"[POSITION] "
                            f"{symbol} "
                            f"qty={qty} "
                            f"PNL={pnl:.2%} "
                            f"TP={TP_PERCENT:.2%} "
                            f"SL={SL_PERCENT:.2%}"
                        )

            except Exception as e:

                print(
                    f"[STATUS ERROR] {e}"
                )

        time.sleep(1)


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print(
        "========================================"
    )
    print(
        "LIVE TRADING ENGINE"
    )
    print(
        "========================================"
    )
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
        f"Take profit: "
        f"{TP_PERCENT:.2%}"
    )

    print(
        f"Stop loss: "
        f"{SL_PERCENT:.2%}"
    )

    print(
        f"Position check: "
        f"{POSITION_CHECK_SECONDS}s"
    )

    print()

    print(
        "ENTRY: market order after live tick crosses trigger"
    )

    print(
        "EXIT: market order based on Alpaca position P&L"
    )

    print(
        "NO Alpaca stop orders"
    )

    print(
        "NO Alpaca take-profit orders"
    )

    print(
        "NO OCO orders"
    )

    print(
        "LONG ONLY"
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
    # POSITION MONITOR
    # --------------------------------------------------------

    position_thread = threading.Thread(
        target=position_monitor,
        daemon=True,
    )

    position_thread.start()

    # --------------------------------------------------------
    # ENTRY MONITOR
    #
    # Mostly redundant because entry is also checked
    # directly from every websocket tick.
    #
    # It acts as a safety net in case a websocket update
    # was received but the immediate check was interrupted.
    # --------------------------------------------------------

    entry_thread = threading.Thread(
        target=entry_monitor,
        daemon=True,
    )

    entry_thread.start()

    # --------------------------------------------------------
    # STATUS MONITOR
    # --------------------------------------------------------

    status_thread = threading.Thread(
        target=status_monitor,
        daemon=True,
    )

    status_thread.start()

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