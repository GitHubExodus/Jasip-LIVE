






import time
import math
import threading
from datetime import datetime, timezone

from alpaca.data.live import StockDataStream
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
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

TRADE_DOLLARS = 100.00

# ------------------------------------------------------------
# ENTRY
# ------------------------------------------------------------

ENTRY_OFFSET = 0.0000001

# ------------------------------------------------------------
# EXIT
# ------------------------------------------------------------

TAKE_PROFIT_PERCENT = 0.01       # +1.00%
STOP_LOSS_PERCENT = -0.005       # -0.50%

# How often we ask Alpaca for positions/P&L.
EXIT_CHECK_SECONDS = 1

# ------------------------------------------------------------
# GENERAL
# ------------------------------------------------------------

PRINT_TICKS = False


# ============================================================
# CLIENT
# ============================================================

trading_client = TradingClient(
    API_KEY,
    API_SECRET,
    paper=ALPACA_PAPER,
)


# ============================================================
# LIVE STATE
# ============================================================

CURRENT_BAR = {
    symbol: None
    for symbol in SYMBOLS
}

CURRENT_MINUTE = {
    symbol: None
    for symbol in SYMBOLS
}


# Current position state according to our program.
IN_POSITION = {
    symbol: False
    for symbol in SYMBOLS
}


# Quantity bought.
POSITION_QTY = {
    symbol: 0
    for symbol in SYMBOLS
}


# Entry price recorded after Alpaca confirms the buy.
ENTRY_PRICE = {
    symbol: None
    for symbol in SYMBOLS
}


# Prevents multiple buy orders while one is being submitted.
ENTRY_ORDER_PENDING = {
    symbol: False
    for symbol in SYMBOLS
}


# Prevents multiple sell orders.
EXIT_ORDER_PENDING = {
    symbol: False
    for symbol in SYMBOLS
}


# Prevents another trade during the same 1-minute bar.
TRADED_THIS_BAR = {
    symbol: False
    for symbol in SYMBOLS
}


STATE_LOCK = threading.Lock()


# ============================================================
# PRICE ROUNDING
# ============================================================

def round_price(price):

    price = float(price)

    if price >= 1.0:
        return round(price, 2)

    return round(price, 4)


# ============================================================
# MINUTE
# ============================================================

def get_minute_timestamp(timestamp):

    return timestamp.replace(
        second=0,
        microsecond=0,
    )


# ============================================================
# CREATE NEW BAR
# ============================================================

def create_new_bar(
    symbol,
    timestamp,
    price,
    size,
):

    minute = get_minute_timestamp(
        timestamp
    )

    CURRENT_BAR[symbol] = {
        "timestamp": minute,
        "open": price,
        "high": price,
        "low": price,
        "close": price,
        "volume": size,
    }

    CURRENT_MINUTE[symbol] = minute

    # New minute = new trade opportunity.
    TRADED_THIS_BAR[symbol] = False

    print(
        f"[BAR] {symbol} "
        f"{minute} "
        f"new 1m bar"
    )


# ============================================================
# UPDATE BAR
# ============================================================

def update_live_bar(data):

    symbol = data.symbol

    if symbol not in CURRENT_BAR:
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

    current_bar = CURRENT_BAR[symbol]

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

    # --------------------------------------------------------
    # SAME MINUTE
    # --------------------------------------------------------

    else:

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

    # --------------------------------------------------------
    # ENTRY CHECK HAPPENS ON EVERY TICK
    # --------------------------------------------------------

    check_entry_tick(
        symbol,
        price,
    )


# ============================================================
# GET CURRENT POSITION FROM ALPACA
# ============================================================

def get_alpaca_position(symbol):

    try:

        position = trading_client.get_open_position(
            symbol
        )

        return position

    except Exception:

        return None


# ============================================================
# GET POSITION PNL %
# ============================================================

def get_position_pnl_percent(symbol):

    position = get_alpaca_position(
        symbol
    )

    if position is None:
        return None

    try:

        pnl_percent = float(
            position.unrealized_plpc
        )

        return pnl_percent

    except Exception as e:

        print(
            f"[PNL ERROR] "
            f"{symbol}: {e}"
        )

        return None


# ============================================================
# SYNC POSITION
# ============================================================

def sync_position(symbol):

    position = get_alpaca_position(
        symbol
    )

    # --------------------------------------------------------
    # NO POSITION
    # --------------------------------------------------------

    if position is None:

        if IN_POSITION[symbol]:

            print(
                f"[POSITION CLOSED] "
                f"{symbol}"
            )

        IN_POSITION[symbol] = False
        POSITION_QTY[symbol] = 0
        ENTRY_PRICE[symbol] = None
        EXIT_ORDER_PENDING[symbol] = False

        return None

    # --------------------------------------------------------
    # POSITION EXISTS
    # --------------------------------------------------------

    try:

        qty = float(
            position.qty
        )

        entry_price = float(
            position.avg_entry_price
        )

        IN_POSITION[symbol] = True

        POSITION_QTY[symbol] = qty

        ENTRY_PRICE[symbol] = entry_price

        return position

    except Exception as e:

        print(
            f"[POSITION SYNC ERROR] "
            f"{symbol}: {e}"
        )

        return None


# ============================================================
# BUY
# ============================================================

def buy_symbol(
    symbol,
    current_price,
):

    if IN_POSITION[symbol]:
        return

    if ENTRY_ORDER_PENDING[symbol]:
        return

    if TRADED_THIS_BAR[symbol]:
        return

    current_price = float(
        current_price
    )

    if current_price <= 0:
        return

    qty = math.floor(
        TRADE_DOLLARS
        / current_price
    )

    if qty < 1:

        print(
            f"[BUY SKIP] "
            f"{symbol}: "
            f"price={current_price:.4f}"
        )

        return

    ENTRY_ORDER_PENDING[symbol] = True

    try:

        request = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )

        order = trading_client.submit_order(
            order_data=request
        )

        order_id = str(
            order.id
        )

        print(
            f"[BUY] "
            f"{symbol} "
            f"qty={qty} "
            f"market={current_price:.4f} "
            f"order={order_id}"
        )

        # ----------------------------------------------------
        # WAIT FOR ALPACA TO FILL
        # ----------------------------------------------------

        wait_for_buy_fill(
            symbol,
            order_id,
        )

    except Exception as e:

        print(
            f"[BUY ERROR] "
            f"{symbol}: {e}"
        )

        ENTRY_ORDER_PENDING[symbol] = False


# ============================================================
# WAIT FOR BUY FILL
# ============================================================

def wait_for_buy_fill(
    symbol,
    order_id,
):

    for _ in range(50):

        try:

            order = (
                trading_client
                .get_order_by_id(order_id)
            )

            status = str(
                order.status
            ).lower()

            # ------------------------------------------------
            # FILLED
            # ------------------------------------------------

            if status == "filled":

                filled_price = float(
                    order.filled_avg_price
                )

                filled_qty = float(
                    order.filled_qty
                )

                with STATE_LOCK:

                    IN_POSITION[symbol] = True

                    POSITION_QTY[symbol] = (
                        filled_qty
                    )

                    ENTRY_PRICE[symbol] = (
                        filled_price
                    )

                    ENTRY_ORDER_PENDING[symbol] = (
                        False
                    )

                    TRADED_THIS_BAR[symbol] = (
                        True
                    )

                print(
                    f"[BUY FILLED] "
                    f"{symbol} "
                    f"qty={filled_qty} "
                    f"price={filled_price:.4f}"
                )

                return

            # ------------------------------------------------
            # DEAD
            # ------------------------------------------------

            if status in {
                "canceled",
                "cancelled",
                "rejected",
                "expired",
            }:

                print(
                    f"[BUY DEAD] "
                    f"{symbol} "
                    f"status={status}"
                )

                ENTRY_ORDER_PENDING[symbol] = False

                return

        except Exception as e:

            print(
                f"[BUY CHECK ERROR] "
                f"{symbol}: {e}"
            )

            ENTRY_ORDER_PENDING[symbol] = False

            return

        time.sleep(0.1)

    print(
        f"[BUY TIMEOUT] "
        f"{symbol} "
        f"order={order_id}"
    )

    ENTRY_ORDER_PENDING[symbol] = False


# ============================================================
# ENTRY CHECK — EVERY TICK
# ============================================================

def check_entry_tick(
    symbol,
    price,
):

    if IN_POSITION[symbol]:
        return

    if ENTRY_ORDER_PENDING[symbol]:
        return

    if TRADED_THIS_BAR[symbol]:
        return

    bar = CURRENT_BAR[symbol]

    if bar is None:
        return

    # --------------------------------------------------------
    # Current 1-minute high.
    #
    # The current tick itself may already become the high.
    # Therefore compare against the PREVIOUS high.
    # --------------------------------------------------------

    previous_high = float(
        bar["high"]
    )

    trigger = round_price(
        previous_high
        + ENTRY_OFFSET
    )

    price = float(price)

    if PRINT_TICKS:

        print(
            f"[TICK] "
            f"{symbol} "
            f"price={price:.4f} "
            f"trigger={trigger:.4f}"
        )

    # --------------------------------------------------------
    # CROSS ABOVE TRIGGER
    # --------------------------------------------------------

    if price >= trigger:

        print(
            f"[BREAKOUT] "
            f"{symbol} "
            f"price={price:.4f} "
            f"trigger={trigger:.4f}"
        )

        # Update high first.
        bar["high"] = max(
            bar["high"],
            price,
        )

        # Buy immediately at market.
        buy_symbol(
            symbol,
            price,
        )


# ============================================================
# SELL
# ============================================================

def sell_symbol(
    symbol,
    reason,
    pnl_percent,
):

    if not IN_POSITION[symbol]:
        return

    if EXIT_ORDER_PENDING[symbol]:
        return

    qty = POSITION_QTY[symbol]

    if qty <= 0:

        print(
            f"[SELL ERROR] "
            f"{symbol}: invalid qty"
        )

        return

    EXIT_ORDER_PENDING[symbol] = True

    try:

        # ----------------------------------------------------
        # Normal market sell.
        # ----------------------------------------------------

        request = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )

        order = trading_client.submit_order(
            order_data=request
        )

        print(
            f"[SELL] "
            f"{symbol} "
            f"qty={qty} "
            f"reason={reason} "
            f"pnl={pnl_percent:.2%} "
            f"order={order.id}"
        )

        # Do NOT immediately mark the position closed.
        # Wait until Alpaca confirms it is actually gone.

    except Exception as e:

        print(
            f"[SELL ERROR] "
            f"{symbol}: {e}"
        )

        EXIT_ORDER_PENDING[symbol] = False


# ============================================================
# CHECK ALL POSITIONS
# ============================================================

def check_position(
    symbol,
):

    position = sync_position(
        symbol
    )

    if position is None:
        return

    # --------------------------------------------------------
    # If a sell order was already submitted, don't submit
    # another one.
    # --------------------------------------------------------

    if EXIT_ORDER_PENDING[symbol]:
        return

    pnl_percent = get_position_pnl_percent(
        symbol
    )

    if pnl_percent is None:
        return

    print(
        f"[PNL] "
        f"{symbol} "
        f"pnl={pnl_percent:.2%} "
        f"entry={ENTRY_PRICE[symbol]:.4f}"
    )

    # --------------------------------------------------------
    # TAKE PROFIT
    # --------------------------------------------------------

    if pnl_percent >= TAKE_PROFIT_PERCENT:

        sell_symbol(
            symbol,
            "TAKE_PROFIT",
            pnl_percent,
        )

        return

    # --------------------------------------------------------
    # STOP LOSS
    # --------------------------------------------------------

    if pnl_percent <= STOP_LOSS_PERCENT:

        sell_symbol(
            symbol,
            "STOP_LOSS",
            pnl_percent,
        )

        return


# ============================================================
# POSITION MONITOR
# ============================================================

def position_monitor():

    while True:

        for symbol in SYMBOLS:

            try:

                with STATE_LOCK:

                    check_position(
                        symbol
                    )

            except Exception as e:

                print(
                    f"[POSITION ERROR] "
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

    if symbol not in CURRENT_BAR:
        return

    with STATE_LOCK:

        update_live_bar(
            data
        )


# ============================================================
# WEBSOCKET WORKER
# ============================================================

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
# STARTUP POSITION SYNC
# ============================================================

def startup_position_sync():

    print()
    print(
        "========================================"
    )
    print(
        "SYNCING EXISTING POSITIONS"
    )
    print(
        "========================================"
    )

    for symbol in SYMBOLS:

        try:

            position = sync_position(
                symbol
            )

            if position is not None:

                pnl = get_position_pnl_percent(
                    symbol
                )

                print(
                    f"[POSITION] "
                    f"{symbol} "
                    f"qty={POSITION_QTY[symbol]} "
                    f"entry={ENTRY_PRICE[symbol]:.4f} "
                    f"pnl="
                    f"{pnl:.2%}"
                    if pnl is not None
                    else
                    f"[POSITION] "
                    f"{symbol} "
                    f"qty={POSITION_QTY[symbol]} "
                    f"entry={ENTRY_PRICE[symbol]:.4f}"
                )

        except Exception as e:

            print(
                f"[STARTUP POSITION ERROR] "
                f"{symbol}: {e}"
            )

    print()


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print(
        "========================================"
    )
    print(
        "SIMPLE LIVE TRADING ENGINE"
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
        f"Entry offset: ${ENTRY_OFFSET:.2f}"
    )

    print(
        f"Take profit: "
        f"{TAKE_PROFIT_PERCENT:.2%}"
    )

    print(
        f"Stop loss: "
        f"{STOP_LOSS_PERCENT:.2%}"
    )

    print()
    print(
        "All stocks are eligible."
    )
    print(
        "Market BUY on breakout."
    )
    print(
        "Market SELL on P&L threshold."
    )
    print(
        "No Alpaca stop orders."
    )
    print(
        "No Alpaca take-profit orders."
    )
    print(
        "No OCO orders."
    )
    print()

    # --------------------------------------------------------
    # EXISTING POSITIONS
    # --------------------------------------------------------

    startup_position_sync()

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

    monitor_thread = threading.Thread(
        target=position_monitor,
        daemon=True,
    )

    monitor_thread.start()

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