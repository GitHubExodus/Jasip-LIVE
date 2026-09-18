
import os
import time
import math
import threading
from datetime import datetime, timezone

import numpy as np

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.live import StockDataStream
from alpaca.data.requests import (
    StockBarsRequest,
    StockLatestTradeRequest,
)
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce


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

# ------------------------------------------------------------
# MANUAL EXIT SETTINGS
# ------------------------------------------------------------

FIXED_TP_PERCENT = 0.01       # +1.00%
FIXED_SL_PERCENT = 0.005      # -0.50%

# ------------------------------------------------------------
# ENTRY SETTINGS
# ------------------------------------------------------------

ENTRY_OFFSET = 0.01

# Number of future bars used by historical breakout analysis.
BREAKOUT_FUTURE_BARS = 3

# Historical data start.
HIST_START = datetime(
    2026,
    1,
    1,
    tzinfo=timezone.utc,
)

# How often the application checks local positions/orders.
ORDER_UPDATE_SECONDS = 1

# How often the program prints status.
STATUS_SECONDS = 5


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
# STATE
# ============================================================

STATE_LOCK = threading.Lock()

# Current 1-minute bar for each symbol.
CURRENT_1M_BAR = {}

# Previous completed 1-minute bar for each symbol.
PREVIOUS_1M_BAR = {}

# Current minute timestamp for each symbol.
CURRENT_MINUTE = {}

# Historical expected breakout profit.
BREAKOUT_STATS = {}

# ------------------------------------------------------------
# LOCAL TRADE STATE
# ------------------------------------------------------------

# symbol ->
# {
#     "status": "ENTRY_PENDING" / "OPEN" / "EXIT_PENDING",
#     "entry_order_id": ...,
#     "exit_order_id": ...,
#     "qty": ...,
#     "entry_price": ...,
#     "take_profit": ...,
#     "stop_loss": ...,
# }
LOCAL_TRADES = {}

# Prevents multiple entry orders during the same breakout.
TRADED_THIS_BAR = {}

# Last live price received.
LAST_PRICE = {}

# Last time status was printed.
LAST_STATUS_PRINT = 0.0

# Prevent multiple websocket reconnect threads.
STREAM_STARTED = False


# ============================================================
# PRICE HELPERS
# ============================================================

def round_price(price):
    """
    Alpaca stock price precision:
    >= $1  -> 2 decimals
    <  $1  -> 4 decimals
    """

    price = float(price)

    if price >= 1.0:
        return round(price, 2)

    return round(price, 4)


def calculate_exit_prices(entry_price):
    """
    Calculate the local TP and SL.

    These values are NOT submitted to Alpaca.
    They exist only inside this program.
    """

    take_profit = entry_price * (1.0 + FIXED_TP_PERCENT)
    stop_loss = entry_price * (1.0 - FIXED_SL_PERCENT)

    return (
        round_price(take_profit),
        round_price(stop_loss),
    )


# ============================================================
# HISTORICAL DATA
# ============================================================

def load_historical_breakout_stats():
    """
    Build the historical expected breakout-profit statistic.

    For every bar:

        previous high
            ->
        breakout above previous high
            ->
        inspect next BREAKOUT_FUTURE_BARS bars
            ->
        calculate maximum future high
            ->
        calculate expected profit

    Result:

        BREAKOUT_STATS[symbol] = average expected profit
    """

    print("\n" + "=" * 70)
    print("LOADING HISTORICAL BREAKOUT STATS")
    print("=" * 70)

    try:
        request = StockBarsRequest(
            symbol_or_symbols=SYMBOLS,
            timeframe=TimeFrame.Minute,
            start=HIST_START,
            feed=DataFeed.IEX,
        )

        bars = historical_client.get_stock_bars(request)

    except Exception as e:
        print(f"[HISTORICAL ERROR] {e}")
        return

    for symbol in SYMBOLS:

        try:
            symbol_bars = bars[symbol]

            if symbol_bars is None:
                BREAKOUT_STATS[symbol] = 0.0
                continue

            highs = np.asarray(
                [float(bar.high) for bar in symbol_bars],
                dtype=np.float64,
            )

            if len(highs) < BREAKOUT_FUTURE_BARS + 2:
                BREAKOUT_STATS[symbol] = 0.0
                continue

            profits = []

            for i in range(1, len(highs) - BREAKOUT_FUTURE_BARS):

                previous_high = highs[i - 1]
                breakout_high = highs[i]

                # Not a breakout.
                if breakout_high <= previous_high:
                    continue

                future_end = i + BREAKOUT_FUTURE_BARS + 1

                future_high = np.max(
                    highs[i + 1:future_end]
                )

                if previous_high <= 0:
                    continue

                expected_profit = (
                    future_high - previous_high
                ) / previous_high

                profits.append(expected_profit)

            if profits:
                BREAKOUT_STATS[symbol] = float(
                    np.mean(profits)
                )
            else:
                BREAKOUT_STATS[symbol] = 0.0

            print(
                f"{symbol:6s} "
                f"expected breakout = "
                f"{BREAKOUT_STATS[symbol] * 100:.3f}%"
            )

        except Exception as e:
            print(
                f"[HIST ERROR] {symbol}: {e}"
            )

            BREAKOUT_STATS[symbol] = 0.0

    print("=" * 70)


# ============================================================
# AUTH
# ============================================================

def verify_alpaca_auth():
    """
    Verify that the trading account is reachable.
    """

    print("\nChecking Alpaca authentication...")

    try:
        account = trading_client.get_account()

        print(
            f"[AUTH OK] "
            f"account={account.account_number} "
            f"status={account.status}"
        )

        return True

    except Exception as e:
        print(f"[AUTH ERROR] {e}")
        return False


# ============================================================
# CURRENT SERVER PRICE
# ============================================================

def get_latest_server_price(symbol):
    """
    Get the latest trade directly from Alpaca.

    This is used as a backup/reference price.
    """

    try:
        request = StockLatestTradeRequest(
            symbol_or_symbols=symbol,
            feed=DataFeed.IEX,
        )

        trades = historical_client.get_stock_latest_trade(
            request
        )

        trade = trades.get(symbol)

        if trade is None:
            return None

        return float(trade.price)

    except Exception as e:
        print(
            f"[PRICE ERROR] {symbol}: {e}"
        )

        return None


# ============================================================
# BAR MANAGEMENT
# ============================================================

def update_1m_bar(symbol, price, timestamp):
    """
    Add a live trade to the current 1-minute bar.
    """

    minute = timestamp.replace(
        second=0,
        microsecond=0,
    )

    with STATE_LOCK:

        LAST_PRICE[symbol] = float(price)

        # ----------------------------------------------------
        # NEW MINUTE
        # ----------------------------------------------------

        if (
            symbol not in CURRENT_MINUTE
            or CURRENT_MINUTE[symbol] != minute
        ):

            # Move current bar to previous bar.
            if symbol in CURRENT_1M_BAR:
                PREVIOUS_1M_BAR[symbol] = (
                    CURRENT_1M_BAR[symbol].copy()
                )

            CURRENT_MINUTE[symbol] = minute

            CURRENT_1M_BAR[symbol] = {
                "timestamp": minute,
                "open": float(price),
                "high": float(price),
                "low": float(price),
                "close": float(price),
            }

            # A new minute means a new entry opportunity.
            TRADED_THIS_BAR[symbol] = False

            return

        # ----------------------------------------------------
        # UPDATE CURRENT BAR
        # ----------------------------------------------------

        bar = CURRENT_1M_BAR[symbol]

        if price > bar["high"]:
            bar["high"] = float(price)

        if price < bar["low"]:
            bar["low"] = float(price)

        bar["close"] = float(price)


# ============================================================
# ENTRY LOGIC
# ============================================================

def check_entry(symbol, price):
    """
    Determine whether this symbol should enter.

    Entry logic:

        previous 1-minute high
                    +
                ENTRY_OFFSET
                    |
                    v
        current live price crosses it

    Once triggered, a MARKET BUY is sent.

    Alpaca does NOT hold a stop-entry order.
    """

    with STATE_LOCK:

        if symbol not in PREVIOUS_1M_BAR:
            return

        if symbol not in CURRENT_1M_BAR:
            return

        # ----------------------------------------------------
        # Already trading this symbol.
        # ----------------------------------------------------

        if symbol in LOCAL_TRADES:
            return

        # ----------------------------------------------------
        # Already entered during this bar.
        # ----------------------------------------------------

        if TRADED_THIS_BAR.get(symbol, False):
            return

        previous_high = float(
            PREVIOUS_1M_BAR[symbol]["high"]
        )

        entry_trigger = round_price(
            previous_high + ENTRY_OFFSET
        )

        expected_profit = BREAKOUT_STATS.get(
            symbol,
            0.0,
        )

        if expected_profit < EXPECTED_THRESHOLD:
            return

        # ----------------------------------------------------
        # No breakout yet.
        # ----------------------------------------------------

        if price < entry_trigger:
            return

        print(
            f"\n[ENTRY TRIGGER] {symbol} "
            f"price={price:.4f} "
            f"trigger={entry_trigger:.4f} "
            f"expected={expected_profit * 100:.3f}%"
        )

        # Reserve the symbol immediately.
        TRADED_THIS_BAR[symbol] = True

        # Create the local pending state.
        LOCAL_TRADES[symbol] = {
            "status": "ENTRY_PENDING",
            "entry_order_id": None,
            "exit_order_id": None,
            "qty": 0,
            "entry_price": None,
            "take_profit": None,
            "stop_loss": None,
        }

    # Submit outside the lock.
    submit_market_entry(
        symbol,
        price,
    )


def submit_market_entry(symbol, reference_price):
    """
    Submit a normal MARKET BUY.

    No stop order.
    No bracket.
    No OCO.
    """

    qty = math.floor(
        TRADE_DOLLARS / reference_price
    )

    if qty <= 0:
        print(
            f"[ENTRY SKIP] {symbol}: "
            f"price too high for ${TRADE_DOLLARS}"
        )

        with STATE_LOCK:
            LOCAL_TRADES.pop(symbol, None)

        return

    try:

        order_request = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )

        order = trading_client.submit_order(
            order_data=order_request
        )

        with STATE_LOCK:
            if symbol in LOCAL_TRADES:
                LOCAL_TRADES[symbol][
                    "entry_order_id"
                ] = str(order.id)

                LOCAL_TRADES[symbol][
                    "qty"
                ] = qty

        print(
            f"[ENTRY ORDER] {symbol} "
            f"BUY {qty} shares "
            f"order={order.id}"
        )

    except Exception as e:

        print(
            f"[ENTRY ERROR] {symbol}: {e}"
        )

        with STATE_LOCK:
            LOCAL_TRADES.pop(symbol, None)
            TRADED_THIS_BAR[symbol] = False


# ============================================================
# ENTRY ORDER MONITOR
# ============================================================

def process_entry_orders():
    """
    Check pending market BUY orders until Alpaca reports
    their actual fill.

    The actual fill price becomes our entry price.
    """

    symbols_to_check = []

    with STATE_LOCK:

        for symbol, trade in LOCAL_TRADES.items():

            if (
                trade["status"] == "ENTRY_PENDING"
                and trade["entry_order_id"] is not None
            ):
                symbols_to_check.append(
                    (
                        symbol,
                        trade["entry_order_id"],
                    )
                )

    for symbol, order_id in symbols_to_check:

        try:

            order = trading_client.get_order_by_id(
                order_id
            )

            status = str(order.status).lower()

            # ------------------------------------------------
            # FILLED
            # ------------------------------------------------

            if status == "filled":

                fill_price = float(
                    order.filled_avg_price
                )

                filled_qty = int(
                    float(order.filled_qty)
                )

                take_profit, stop_loss = (
                    calculate_exit_prices(
                        fill_price
                    )
                )

                with STATE_LOCK:

                    if symbol not in LOCAL_TRADES:
                        continue

                    LOCAL_TRADES[symbol].update({
                        "status": "OPEN",
                        "qty": filled_qty,
                        "entry_price": fill_price,
                        "take_profit": take_profit,
                        "stop_loss": stop_loss,
                    })

                print(
                    f"\n[ENTRY FILLED] {symbol}"
                )

                print(
                    f"  qty         = {filled_qty}"
                )

                print(
                    f"  entry       = {fill_price:.4f}"
                )

                print(
                    f"  TAKE PROFIT = {take_profit:.4f} "
                    f"(+{FIXED_TP_PERCENT * 100:.2f}%)"
                )

                print(
                    f"  STOP LOSS   = {stop_loss:.4f} "
                    f"(-{FIXED_SL_PERCENT * 100:.2f}%)"
                )

            # ------------------------------------------------
            # FAILED
            # ------------------------------------------------

            elif status in {
                "canceled",
                "cancelled",
                "rejected",
                "expired",
            }:

                print(
                    f"[ENTRY FAILED] {symbol} "
                    f"status={status}"
                )

                with STATE_LOCK:
                    LOCAL_TRADES.pop(symbol, None)

            # ------------------------------------------------
            # STILL WORKING
            # ------------------------------------------------

            else:

                pass

        except Exception as e:

            print(
                f"[ENTRY CHECK ERROR] "
                f"{symbol}: {e}"
            )


# ============================================================
# MANUAL EXIT LOGIC
# ============================================================

def check_exit(symbol, price):
    """
    Manually manage TP/SL.

    This is the critical part.

    The program itself determines:

        price >= TP
            -> SELL

        price <= SL
            -> SELL

    No stop-loss or take-profit order exists at Alpaca.
    """

    with STATE_LOCK:

        trade = LOCAL_TRADES.get(symbol)

        if trade is None:
            return

        if trade["status"] != "OPEN":
            return

        entry_price = trade["entry_price"]
        take_profit = trade["take_profit"]
        stop_loss = trade["stop_loss"]
        qty = trade["qty"]

        if (
            entry_price is None
            or take_profit is None
            or stop_loss is None
            or qty <= 0
        ):
            return

        # ----------------------------------------------------
        # TAKE PROFIT
        # ----------------------------------------------------

        if price >= take_profit:

            print(
                f"\n[TP TRIGGER] {symbol} "
                f"price={price:.4f} "
                f"TP={take_profit:.4f}"
            )

            trade["status"] = "EXIT_PENDING"

            exit_reason = "TP"

        # ----------------------------------------------------
        # STOP LOSS
        # ----------------------------------------------------

        elif price <= stop_loss:

            print(
                f"\n[SL TRIGGER] {symbol} "
                f"price={price:.4f} "
                f"SL={stop_loss:.4f}"
            )

            trade["status"] = "EXIT_PENDING"

            exit_reason = "SL"

        else:
            return

    # Submit outside lock.
    submit_market_exit(
        symbol,
        qty,
        exit_reason,
    )


def submit_market_exit(symbol, qty, reason):
    """
    Submit a normal MARKET SELL.

    Alpaca is only executing the sell.
    Python decided that the position should be closed.
    """

    try:

        order_request = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )

        order = trading_client.submit_order(
            order_data=order_request
        )

        with STATE_LOCK:

            if symbol in LOCAL_TRADES:
                LOCAL_TRADES[symbol][
                    "exit_order_id"
                ] = str(order.id)

        print(
            f"[EXIT ORDER] {symbol} "
            f"SELL {qty} "
            f"reason={reason} "
            f"order={order.id}"
        )

    except Exception as e:

        print(
            f"[EXIT ERROR] {symbol}: {e}"
        )

        # We do NOT delete the position.
        #
        # The position is still open.
        # Keep it locally OPEN so the program
        # can try again.

        with STATE_LOCK:

            if symbol in LOCAL_TRADES:
                LOCAL_TRADES[symbol][
                    "status"
                ] = "OPEN"


# ============================================================
# EXIT ORDER MONITOR
# ============================================================

def process_exit_orders():
    """
    Wait for the market SELL to actually fill.
    """

    symbols_to_check = []

    with STATE_LOCK:

        for symbol, trade in LOCAL_TRADES.items():

            if (
                trade["status"] == "EXIT_PENDING"
                and trade["exit_order_id"] is not None
            ):
                symbols_to_check.append(
                    (
                        symbol,
                        trade["exit_order_id"],
                    )
                )

    for symbol, order_id in symbols_to_check:

        try:

            order = trading_client.get_order_by_id(
                order_id
            )

            status = str(order.status).lower()

            # ------------------------------------------------
            # FILLED
            # ------------------------------------------------

            if status == "filled":

                exit_price = float(
                    order.filled_avg_price
                )

                with STATE_LOCK:

                    trade = LOCAL_TRADES.get(
                        symbol
                    )

                    if trade is None:
                        continue

                    entry_price = float(
                        trade["entry_price"]
                    )

                    qty = float(
                        trade["qty"]
                    )

                    pnl_percent = (
                        (exit_price - entry_price)
                        / entry_price
                    )

                    pnl_dollars = (
                        exit_price - entry_price
                    ) * qty

                    print(
                        f"\n[EXIT FILLED] {symbol}"
                    )

                    print(
                        f"  qty       = {qty:g}"
                    )

                    print(
                        f"  entry     = {entry_price:.4f}"
                    )

                    print(
                        f"  exit      = {exit_price:.4f}"
                    )

                    print(
                        f"  return    = "
                        f"{pnl_percent * 100:.3f}%"
                    )

                    print(
                        f"  P/L       = "
                        f"${pnl_dollars:.2f}"
                    )

                    # Completely remove local position.
                    LOCAL_TRADES.pop(symbol, None)

            # ------------------------------------------------
            # FAILED
            # ------------------------------------------------

            elif status in {
                "canceled",
                "cancelled",
                "rejected",
                "expired",
            }:

                print(
                    f"[EXIT FAILED] {symbol} "
                    f"status={status}"
                )

                # Position still exists.
                # Return it to OPEN so the local
                # TP/SL monitor continues working.

                with STATE_LOCK:

                    if symbol in LOCAL_TRADES:

                        LOCAL_TRADES[symbol][
                            "status"
                        ] = "OPEN"

                        LOCAL_TRADES[symbol][
                            "exit_order_id"
                        ] = None

        except Exception as e:

            print(
                f"[EXIT CHECK ERROR] "
                f"{symbol}: {e}"
            )


# ============================================================
# RECONCILE EXISTING ALPACA POSITIONS
# ============================================================

def reconcile_existing_positions():
    """
    Important safety feature.

    If the program restarts while a position is already open,
    discover that position from Alpaca and begin managing it
    locally.

    This means an existing position is not ignored.
    """

    print("\nChecking existing Alpaca positions...")

    try:

        positions = trading_client.get_all_positions()

    except Exception as e:

        print(
            f"[POSITION ERROR] {e}"
        )

        return

    for position in positions:

        symbol = str(
            position.symbol
        )

        if symbol not in SYMBOLS:
            continue

        try:

            qty = int(
                float(position.qty)
            )

            entry_price = float(
                position.avg_entry_price
            )

            if qty <= 0:
                continue

            take_profit, stop_loss = (
                calculate_exit_prices(
                    entry_price
                )
            )

            with STATE_LOCK:

                LOCAL_TRADES[symbol] = {
                    "status": "OPEN",
                    "entry_order_id": None,
                    "exit_order_id": None,
                    "qty": qty,
                    "entry_price": entry_price,
                    "take_profit": take_profit,
                    "stop_loss": stop_loss,
                }

            print(
                f"[POSITION RECOVERED] {symbol} "
                f"qty={qty} "
                f"entry={entry_price:.4f} "
                f"TP={take_profit:.4f} "
                f"SL={stop_loss:.4f}"
            )

        except Exception as e:

            print(
                f"[POSITION RECOVERY ERROR] "
                f"{symbol}: {e}"
            )


# ============================================================
# WEBSOCKET
# ============================================================

def websocket_worker():
    """
    Alpaca websocket receives live trades.

    Every trade:

        1. updates local price
        2. updates 1-minute bar
        3. checks entry
        4. checks TP/SL
    """

    global STREAM_STARTED

    if STREAM_STARTED:
        return

    STREAM_STARTED = True

    while True:

        try:

            print(
                "\nStarting Alpaca market-data stream..."
            )

            stream = StockDataStream(
                API_KEY,
                API_SECRET,
                feed=DataFeed.IEX,
            )

            async def handle_trade(trade):

                try:

                    symbol = str(
                        trade.symbol
                    )

                    price = float(
                        trade.price
                    )

                    timestamp = trade.timestamp

                    if timestamp is None:
                        timestamp = datetime.now(
                            timezone.utc
                        )

                    # ----------------------------------------
                    # Update local market data.
                    # ----------------------------------------

                    update_1m_bar(
                        symbol,
                        price,
                        timestamp,
                    )

                    # ----------------------------------------
                    # ENTRY
                    # ----------------------------------------

                    check_entry(
                        symbol,
                        price,
                    )

                    # ----------------------------------------
                    # EXIT
                    # ----------------------------------------

                    check_exit(
                        symbol,
                        price,
                    )

                except Exception as e:

                    print(
                        f"[TRADE HANDLER ERROR] "
                        f"{e}"
                    )

            stream.subscribe_trades(
                handle_trade,
                *SYMBOLS,
            )

            print(
                "Websocket connected."
            )

            stream.run()

        except Exception as e:

            print(
                f"[WEBSOCKET ERROR] {e}"
            )

            print(
                "Retrying websocket in 5 seconds..."
            )

            time.sleep(5)


# ============================================================
# ORDER MONITOR
# ============================================================

def order_monitor_worker():
    """
    Continuously monitors:

        entry market orders
        exit market orders
    """

    while True:

        try:

            process_entry_orders()
            process_exit_orders()

        except Exception as e:

            print(
                f"[ORDER MONITOR ERROR] {e}"
            )

        time.sleep(
            ORDER_UPDATE_SECONDS
        )


# ============================================================
# POSITION SAFETY MONITOR
# ============================================================

def position_safety_worker():
    """
    Backup monitor.

    If websocket data misses something, this periodically
    checks Alpaca's latest trade for every locally-open position.

    This is NOT used as the primary price source.
    The websocket remains primary.
    """

    while True:

        try:

            with STATE_LOCK:

                open_symbols = [
                    symbol
                    for symbol, trade
                    in LOCAL_TRADES.items()
                    if trade["status"] == "OPEN"
                ]

            for symbol in open_symbols:

                price = get_latest_server_price(
                    symbol
                )

                if price is None:
                    continue

                with STATE_LOCK:
                    LAST_PRICE[symbol] = price

                check_exit(
                    symbol,
                    price,
                )

                time.sleep(0.05)

        except Exception as e:

            print(
                f"[SAFETY MONITOR ERROR] {e}"
            )

        time.sleep(1)


# ============================================================
# STATUS
# ============================================================

def status_worker():
    """
    Print current local trading state.
    """

    global LAST_STATUS_PRINT

    while True:

        try:

            now = time.time()

            if (
                now - LAST_STATUS_PRINT
                < STATUS_SECONDS
            ):
                time.sleep(1)
                continue

            LAST_STATUS_PRINT = now

            with STATE_LOCK:

                trades = {
                    symbol: data.copy()
                    for symbol, data
                    in LOCAL_TRADES.items()
                }

                prices = LAST_PRICE.copy()

            if trades:

                print(
                    "\n" + "-" * 70
                )

                print(
                    "LOCAL POSITIONS"
                )

                for symbol, trade in trades.items():

                    price = prices.get(
                        symbol,
                        0.0,
                    )

                    entry = trade.get(
                        "entry_price"
                    )

                    tp = trade.get(
                        "take_profit"
                    )

                    sl = trade.get(
                        "stop_loss"
                    )

                    if (
                        entry is not None
                        and price > 0
                    ):

                        pnl = (
                            (price - entry)
                            / entry
                            * 100
                        )

                        print(
                            f"{symbol:6s} "
                            f"status={trade['status']:14s} "
                            f"price={price:.4f} "
                            f"entry={entry:.4f} "
                            f"P/L={pnl:+.2f}% "
                            f"TP={tp:.4f} "
                            f"SL={sl:.4f}"
                        )

                    else:

                        print(
                            f"{symbol:6s} "
                            f"status={trade['status']}"
                        )

                print(
                    "-" * 70
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

    print(
        "\n" + "=" * 70
    )

    print(
        "ALPACA MANUAL-EXIT LIVE TRADER"
    )

    print(
        "=" * 70
    )

    print(
        f"Paper Trading       : {ALPACA_PAPER}"
    )

    print(
        f"Trade Dollars       : ${TRADE_DOLLARS:.2f}"
    )

    print(
        f"Fixed TP            : "
        f"+{FIXED_TP_PERCENT * 100:.2f}%"
    )

    print(
        f"Fixed SL            : "
        f"-{FIXED_SL_PERCENT * 100:.2f}%"
    )

    print(
        "Alpaca TP/SL Orders : DISABLED"
    )

    print(
        "Entry Stop Orders   : DISABLED"
    )

    print(
        "Entry Type          : MARKET"
    )

    print(
        "Exit Type           : MARKET"
    )

    print(
        "=" * 70
    )

    # --------------------------------------------------------
    # AUTH
    # --------------------------------------------------------

    if not verify_alpaca_auth():

        print(
            "Authentication failed."
        )

        return

    # --------------------------------------------------------
    # HISTORICAL DATA
    # --------------------------------------------------------

    load_historical_breakout_stats()

    # --------------------------------------------------------
    # RECOVER EXISTING POSITIONS
    # --------------------------------------------------------

    reconcile_existing_positions()

    # --------------------------------------------------------
    # START WEBSOCKET
    # --------------------------------------------------------

    websocket_thread = threading.Thread(
        target=websocket_worker,
        daemon=True,
    )

    websocket_thread.start()

    # --------------------------------------------------------
    # START ORDER MONITOR
    # --------------------------------------------------------

    order_thread = threading.Thread(
        target=order_monitor_worker,
        daemon=True,
    )

    order_thread.start()

    # --------------------------------------------------------
    # START BACKUP PRICE MONITOR
    # --------------------------------------------------------

    safety_thread = threading.Thread(
        target=position_safety_worker,
        daemon=True,
    )

    safety_thread.start()

    # --------------------------------------------------------
    # START STATUS
    # --------------------------------------------------------

    status_thread = threading.Thread(
        target=status_worker,
        daemon=True,
    )

    status_thread.start()

    print(
        "\nLIVE SYSTEM RUNNING."
    )

    print(
        "Python is now responsible for entry, TP, and SL."
    )

    print(
        "Keep this process running while positions are open."
    )

    # --------------------------------------------------------
    # KEEP ALIVE
    # --------------------------------------------------------

    while True:

        time.sleep(60)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()