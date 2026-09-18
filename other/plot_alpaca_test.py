


import asyncio
import math
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from dash import Dash, dcc, html, Input, Output, State

from alpaca.data.live import StockDataStream
from alpaca.data.enums import DataFeed
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import (
    OrderSide,
    TimeInForce,
    OrderClass,
    AssetStatus,
)
from alpaca.trading.requests import (
    MarketOrderRequest,
    TakeProfitRequest,
    StopLossRequest,
)


# ============================================================
# CONFIG
# ============================================================

API_KEY = "PKA4A6THLEKI6QD2MQPOAO25J3"
SECRET_KEY = "4nj9w53vMrNKJGZsHqN7Siqy34z2Gis9TffWi2beszNU"

ALPACA_PAPER = True
DATA_FEED = DataFeed.IEX

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

TRADE_DOLLARS = 100.0

EXPECTED_MINIMUM = 0.02

EMA_FAST = 3
EMA_SLOW = 5

SECONDS_PER_BAR = 10

MAX_RAW_TICKS_PER_SYMBOL = 100_000

DASH_PORT = 8050


# ============================================================
# ALPACA
# ============================================================

TRADING_CLIENT = TradingClient(
    API_KEY,
    SECRET_KEY,
    paper=ALPACA_PAPER,
)


# ============================================================
# DATA STORAGE
# ============================================================

RAW_TRADES = {
    symbol: []
    for symbol in SYMBOLS
}

RAW_TRADES_LOCK = threading.Lock()


BARS_10S = {
    symbol: pd.DataFrame(
        columns=["open", "high", "low", "close", "volume"]
    )
    for symbol in SYMBOLS
}

BARS_10S_LOCK = threading.Lock()


BARS_1M = {
    symbol: pd.DataFrame(
        columns=["open", "high", "low", "close", "volume"]
    )
    for symbol in SYMBOLS
}

BARS_1M_LOCK = threading.Lock()


# ============================================================
# HISTORICAL / BACKTEST STATISTICS
# ============================================================

EXPECTED_STATS_10S = {
    symbol: {
        "long_profits": [],
        "short_profits": [],
        "long_average": 0.0,
        "short_average": 0.0,
    }
    for symbol in SYMBOLS
}


EXPECTED_STATS_1M = {
    symbol: {
        "long_profits": [],
        "short_profits": [],
        "long_average": 0.0,
        "short_average": 0.0,
    }
    for symbol in SYMBOLS
}


# ============================================================
# STRATEGY 1 STATE
# ============================================================

EMA_STATE_10S = {
    symbol: {
        "fast": None,
        "slow": None,
        "previous_relation": None,
        "active_long": None,
        "active_short": None,
    }
    for symbol in SYMBOLS
}


# ============================================================
# STRATEGY 2 STATE
# ============================================================

BREAKOUT_STATE_1M = {
    symbol: {
        "previous_high": None,
        "previous_low": None,
        "pending_long": [],
        "pending_short": [],
    }
    for symbol in SYMBOLS
}


# ============================================================
# LIVE SIGNAL STATE
# ============================================================

LAST_SIGNAL = {}

LAST_SIGNAL_LOCK = threading.Lock()


# ============================================================
# REAL TRADES
# ============================================================

REAL_TRADES = []

REAL_TRADES_LOCK = threading.Lock()


# ============================================================
# UTILITY
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def calculate_quantity(price):
    if price <= 0:
        return 0

    return int(math.floor(TRADE_DOLLARS / price))


def safe_mean(values):
    if not values:
        return 0.0

    return float(np.mean(np.asarray(values, dtype=np.float64)))


def percent(value):
    return value * 100.0


# ============================================================
# RAW WEBSOCKET TRADE
# ============================================================

def on_trade(data):
    """
    Receives an individual Alpaca websocket trade.

    The raw trade is stored temporarily and later aggregated
    into 10-second bars.
    """

    symbol = data.symbol

    timestamp = pd.Timestamp(data.timestamp)

    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")

    price = float(data.price)
    size = float(data.size)

    with RAW_TRADES_LOCK:

        RAW_TRADES[symbol].append(
            (
                timestamp,
                price,
                size,
            )
        )

        if len(RAW_TRADES[symbol]) > MAX_RAW_TICKS_PER_SYMBOL:
            RAW_TRADES[symbol] = RAW_TRADES[symbol][
                -MAX_RAW_TICKS_PER_SYMBOL:
            ]


# ============================================================
# BUILD 10 SECOND BARS
# ============================================================

def build_10_second_bars(symbol):
    """
    Converts incoming websocket trades into 10-second OHLCV bars.

    Only completed bars are returned.
    """

    with RAW_TRADES_LOCK:

        trades = list(RAW_TRADES[symbol])

    if not trades:
        return None

    df = pd.DataFrame(
        trades,
        columns=[
            "timestamp",
            "price",
            "size",
        ],
    )

    df["timestamp"] = pd.to_datetime(
        df["timestamp"],
        utc=True,
    )

    df = df.set_index("timestamp")

    bars = df.resample("10s").agg(
        open=("price", "first"),
        high=("price", "max"),
        low=("price", "min"),
        close=("price", "last"),
        volume=("size", "sum"),
    )

    bars = bars.dropna(
        subset=["open", "high", "low", "close"]
    )

    return bars


# ============================================================
# UPDATE 10 SECOND HISTORY
# ============================================================

def update_10_second_history(symbol):
    bars = build_10_second_bars(symbol)

    if bars is None or bars.empty:
        return None

    with BARS_10S_LOCK:

        existing = BARS_10S[symbol]

        combined = pd.concat(
            [
                existing,
                bars,
            ]
        )

        combined = combined[
            ~combined.index.duplicated(
                keep="last"
            )
        ]

        combined = combined.sort_index()

        BARS_10S[symbol] = combined

    return bars


# ============================================================
# EMA CALCULATION
# ============================================================

def update_ema_state(symbol, close):
    """
    Incrementally updates EMA 3 and EMA 5.

    No full historical recalculation is required.
    """

    state = EMA_STATE_10S[symbol]

    alpha_fast = 2.0 / (EMA_FAST + 1.0)
    alpha_slow = 2.0 / (EMA_SLOW + 1.0)

    if state["fast"] is None:
        state["fast"] = close
    else:
        state["fast"] = (
            alpha_fast * close
            + (1.0 - alpha_fast) * state["fast"]
        )

    if state["slow"] is None:
        state["slow"] = close
    else:
        state["slow"] = (
            alpha_slow * close
            + (1.0 - alpha_slow) * state["slow"]
        )

    fast = state["fast"]
    slow = state["slow"]

    if fast > slow:
        relation = "above"
    elif fast < slow:
        relation = "below"
    else:
        relation = state["previous_relation"]

    previous_relation = state["previous_relation"]

    cross_up = (
        previous_relation == "below"
        and relation == "above"
    )

    cross_down = (
        previous_relation == "above"
        and relation == "below"
    )

    state["previous_relation"] = relation

    return (
        fast,
        slow,
        cross_up,
        cross_down,
    )


# ============================================================
# STRATEGY 1 HISTORICAL EMA
# ============================================================

def process_ema_history_bar(
    symbol,
    timestamp,
    high,
    low,
    close,
):
    """
    Continuously builds the historical EMA strategy
    from incoming 10-second websocket bars.

    A long starts on cross-up and ends on the next
    cross-down.

    A short starts on cross-down and ends on the next
    cross-up.

    Maximum profit is calculated over the completed
    hypothetical trade.
    """

    (
        fast,
        slow,
        cross_up,
        cross_down,
    ) = update_ema_state(
        symbol,
        close,
    )

    state = EMA_STATE_10S[symbol]

    # --------------------------------------------------------
    # CLOSE LONG
    # --------------------------------------------------------

    if cross_down:

        active_long = state["active_long"]

        if active_long is not None:

            entry = active_long["entry"]

            maximum_high = active_long["maximum_high"]

            profit = (
                maximum_high - entry
            ) / entry

            if profit >= 0:

                EXPECTED_STATS_10S[symbol][
                    "long_profits"
                ].append(profit)

                EXPECTED_STATS_10S[symbol][
                    "long_average"
                ] = safe_mean(
                    EXPECTED_STATS_10S[symbol][
                        "long_profits"
                    ]
                )

            state["active_long"] = None

    # --------------------------------------------------------
    # CLOSE SHORT
    # --------------------------------------------------------

    if cross_up:

        active_short = state["active_short"]

        if active_short is not None:

            entry = active_short["entry"]

            minimum_low = active_short["minimum_low"]

            profit = (
                entry - minimum_low
            ) / entry

            if profit >= 0:

                EXPECTED_STATS_10S[symbol][
                    "short_profits"
                ].append(profit)

                EXPECTED_STATS_10S[symbol][
                    "short_average"
                ] = safe_mean(
                    EXPECTED_STATS_10S[symbol][
                        "short_profits"
                    ]
                )

            state["active_short"] = None

    # --------------------------------------------------------
    # OPEN LONG
    # --------------------------------------------------------

    if cross_up:

        state["active_long"] = {
            "timestamp": timestamp,
            "entry": close,
            "maximum_high": high,
        }

    # --------------------------------------------------------
    # OPEN SHORT
    # --------------------------------------------------------

    if cross_down:

        state["active_short"] = {
            "timestamp": timestamp,
            "entry": close,
            "minimum_low": low,
        }

    # --------------------------------------------------------
    # UPDATE ACTIVE LONG
    # --------------------------------------------------------

    active_long = state["active_long"]

    if active_long is not None:

        if high > active_long["maximum_high"]:
            active_long["maximum_high"] = high

    # --------------------------------------------------------
    # UPDATE ACTIVE SHORT
    # --------------------------------------------------------

    active_short = state["active_short"]

    if active_short is not None:

        if low < active_short["minimum_low"]:
            active_short["minimum_low"] = low


# ============================================================
# BUILD 1 MINUTE BARS
# ============================================================

def update_1_minute_history(symbol):
    """
    Builds 1-minute bars from the collected 10-second bars.
    """

    with BARS_10S_LOCK:

        bars_10s = BARS_10S[symbol].copy()

    if bars_10s.empty:
        return None

    bars_1m = bars_10s.resample("1min").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )

    bars_1m = bars_1m.dropna(
        subset=[
            "open",
            "high",
            "low",
            "close",
        ]
    )

    with BARS_1M_LOCK:

        existing = BARS_1M[symbol]

        combined = pd.concat(
            [
                existing,
                bars_1m,
            ]
        )

        combined = combined[
            ~combined.index.duplicated(
                keep="last"
            )
        ]

        combined = combined.sort_index()

        BARS_1M[symbol] = combined

    return bars_1m


# ============================================================
# STRATEGY 2 HISTORICAL BREAKOUT
# ============================================================

def process_breakout_history_bar(
    symbol,
    timestamp,
    high,
    low,
):
    """
    Continuously builds the historical breakout statistics.

    Long:
        current high > previous high

    Short:
        current low < previous low

    Each setup waits for the current candle plus
    three future completed candles.

    The maximum favorable excursion is then recorded.
    """

    state = BREAKOUT_STATE_1M[symbol]

    previous_high = state["previous_high"]
    previous_low = state["previous_low"]

    # --------------------------------------------------------
    # UPDATE EXISTING LONG SETUPS
    # --------------------------------------------------------

    for setup in state["pending_long"]:

        setup["highs"].append(high)

    # --------------------------------------------------------
    # UPDATE EXISTING SHORT SETUPS
    # --------------------------------------------------------

    for setup in state["pending_short"]:

        setup["lows"].append(low)

    # --------------------------------------------------------
    # AGE LONG SETUPS
    # --------------------------------------------------------

    completed_long = []

    for setup in state["pending_long"]:

        setup["future_completed"] += 1

        if setup["future_completed"] >= 3:

            entry = setup["entry"]

            maximum_high = max(
                setup["highs"]
            )

            profit = (
                maximum_high - entry
            ) / entry

            if profit >= 0:

                EXPECTED_STATS_1M[symbol][
                    "long_profits"
                ].append(profit)

                EXPECTED_STATS_1M[symbol][
                    "long_average"
                ] = safe_mean(
                    EXPECTED_STATS_1M_1M_PROFITS(
                        symbol,
                        "long",
                    )
                )

            completed_long.append(setup)

    if completed_long:

        state["pending_long"] = [
            setup
            for setup in state["pending_long"]
            if setup not in completed_long
        ]

    # --------------------------------------------------------
    # AGE SHORT SETUPS
    # --------------------------------------------------------

    completed_short = []

    for setup in state["pending_short"]:

        setup["future_completed"] += 1

        if setup["future_completed"] >= 3:

            entry = setup["entry"]

            minimum_low = min(
                setup["lows"]
            )

            profit = (
                entry - minimum_low
            ) / entry

            if profit >= 0:

                EXPECTED_STATS_1M[symbol][
                    "short_profits"
                ].append(profit)

                EXPECTED_STATS_1M[symbol][
                    "short_average"
                ] = safe_mean(
                    EXPECTED_STATS_1M_1M_PROFITS(
                        symbol,
                        "short",
                    )
                )

            completed_short.append(setup)

    if completed_short:

        state["pending_short"] = [
            setup
            for setup in state["pending_short"]
            if setup not in completed_short
        ]

    # --------------------------------------------------------
    # NEW LONG BREAKOUT
    # --------------------------------------------------------

    if (
        previous_high is not None
        and high > previous_high
    ):

        state["pending_long"].append(
            {
                "timestamp": timestamp,
                "entry": previous_high,
                "highs": [
                    previous_high,
                    high,
                ],
                "future_completed": 0,
            }
        )

    # --------------------------------------------------------
    # NEW SHORT BREAKOUT
    # --------------------------------------------------------

    if (
        previous_low is not None
        and low < previous_low
    ):

        state["pending_short"].append(
            {
                "timestamp": timestamp,
                "entry": previous_low,
                "lows": [
                    previous_low,
                    low,
                ],
                "future_completed": 0,
            }
        )

    state["previous_high"] = high
    state["previous_low"] = low


def EXPECTED_STATS_1M_PROFITS(
    symbol,
    direction,
):
    return EXPECTED_STATS_1M[symbol][
        f"{direction}_profits"
    ]


# ============================================================
# PROCESS COMPLETED 10 SECOND BAR
# ============================================================

def process_10_second_bar(
    symbol,
    timestamp,
    row,
):
    """
    This is the central 10-second processing step.

    One incoming completed 10-second candle is used for:

        1. EMA historical/backtest calculation
        2. live EMA signal calculation
        3. construction of 1-minute data
    """

    process_ema_history_bar(
        symbol,
        timestamp,
        float(row["high"]),
        float(row["low"]),
        float(row["close"]),
    )


# ============================================================
# UPDATE ALL LIVE DATA
# ============================================================

def update_symbol_data(symbol):
    """
    Called continuously.

    WebSocket trades
        -> 10 second bars
        -> EMA strategy
        -> 1 minute bars
        -> breakout strategy
    """

    bars = update_10_second_history(symbol)

    if bars is None or bars.empty:
        return

    # Only process bars that have not already been processed.
    with BARS_10S_LOCK:

        history = BARS_10S[symbol]

    for timestamp, row in bars.iterrows():

        process_10_second_bar(
            symbol,
            timestamp,
            row,
        )

    # Build the current 1-minute history.
    bars_1m = update_1_minute_history(symbol)

    if bars_1m is None or bars_1m.empty:
        return

    # --------------------------------------------------------
    # PROCESS ONLY NEW COMPLETED 1-MINUTE BARS
    # --------------------------------------------------------

    for timestamp, row in bars_1m.iterrows():

        process_breakout_history_bar(
            symbol,
            timestamp,
            float(row["high"]),
            float(row["low"]),
        )


# ============================================================
# EXPECTED PROFIT
# ============================================================

def get_expected_profit(
    symbol,
    strategy,
    side,
):
    if strategy == "EMA_10S":

        if side == "long":
            return EXPECTED_STATS_10S[symbol][
                "long_average"
            ]

        return EXPECTED_STATS_10S[symbol][
            "short_average"
        ]

    if strategy == "BREAKOUT_1M":

        if side == "long":
            return EXPECTED_STATS_1M[symbol][
                "long_average"
            ]

        return EXPECTED_STATS_1M[symbol][
            "short_average"
        ]

    return 0.0


# ============================================================
# ORDER PRICE CALCULATION
# ============================================================

def calculate_exit_prices(
    entry_price,
    expected_profit,
    side,
):
    """
    Expected profit:
        2.40% -> TP = 1.20%, SL = 0.60%

    Alpaca requires the exit price to be at least
    $0.01 away from the base price for these assets.

    Therefore the minimum dollar distance is enforced.
    """

    tp_percent = expected_profit / 2.0

    sl_percent = tp_percent / 2.0

    tp_distance = entry_price * tp_percent
    sl_distance = entry_price * sl_percent

    minimum_distance = 0.01

    tp_distance = max(
        tp_distance,
        minimum_distance,
    )

    sl_distance = max(
        sl_distance,
        minimum_distance,
    )

    if side == "long":

        take_profit = (
            entry_price + tp_distance
        )

        stop_loss = (
            entry_price - sl_distance
        )

    else:

        take_profit = (
            entry_price - tp_distance
        )

        stop_loss = (
            entry_price + sl_distance
        )

    # Alpaca supports fractional-priced stocks,
    # but the requested minimum distance is one cent.
    take_profit = round(
        take_profit,
        4,
    )

    stop_loss = round(
        stop_loss,
        4,
    )

    # Final directional safety check.
    if side == "long":

        if take_profit < entry_price + 0.01:
            take_profit = round(
                entry_price + 0.01,
                4,
            )

        if stop_loss > entry_price - 0.01:
            stop_loss = round(
                entry_price - 0.01,
                4,
            )

    else:

        if take_profit > entry_price - 0.01:
            take_profit = round(
                entry_price - 0.01,
                4,
            )

        if stop_loss < entry_price + 0.01:
            stop_loss = round(
                entry_price + 0.01,
                4,
            )

    # Cannot have a negative/zero exit price.
    if take_profit <= 0:
        return None

    if stop_loss <= 0:
        return None

    return (
        take_profit,
        stop_loss,
    )


# ============================================================
# CHECK SHORTABILITY
# ============================================================

def can_short(symbol):
    """
    Prevents the TNMG-style Alpaca error before
    submitting the order.
    """

    try:

        asset = TRADING_CLIENT.get_asset(
            symbol
        )

        return bool(
            asset.tradable
            and asset.shortable
        )

    except Exception as exc:

        print(
            f"{symbol} | unable to verify shortability: {exc}"
        )

        # Fail closed.
        return False


# ============================================================
# EXPOSURE CHECK
# ============================================================

def symbol_has_exposure(symbol):
    try:

        positions = TRADING_CLIENT.get_all_positions()

        for position in positions:

            if position.symbol == symbol:

                try:
                    qty = float(
                        position.qty
                    )
                except Exception:
                    qty = 0.0

                if qty != 0:
                    return True

        orders = TRADING_CLIENT.get_orders()

        for order in orders:

            if order.symbol != symbol:
                continue

            if order.status in {
                "new",
                "accepted",
                "pending_new",
                "partially_filled",
            }:

                return True

        return False

    except Exception as exc:

        print(
            f"{symbol} | exposure check failed: {exc}"
        )

        return True


# ============================================================
# PLACE BRACKET ORDER
# ============================================================

def place_bracket_order(
    symbol,
    side,
    market_price,
    expected_profit,
    strategy,
):
    """
    Creates the Alpaca bracket order.

    The live strategy only creates the entry.
    Alpaca manages TP and SL.
    """

    quantity = calculate_quantity(
        market_price
    )

    if quantity <= 0:

        print(
            f"{symbol} | {strategy} | "
            f"{side.upper()} skipped | "
            f"price too high for ${TRADE_DOLLARS} allocation"
        )

        return False

    # --------------------------------------------------------
    # SHORTABILITY
    # --------------------------------------------------------

    if side == "short":

        if not can_short(symbol):

            print(
                f"{symbol} | {strategy} | "
                f"SHORT skipped | asset is not shortable"
            )

            return False

    # --------------------------------------------------------
    # EXIT PRICES
    # --------------------------------------------------------

    prices = calculate_exit_prices(
        market_price,
        expected_profit,
        side,
    )

    if prices is None:

        print(
            f"{symbol} | {strategy} | "
            f"{side.upper()} skipped | invalid TP/SL prices"
        )

        return False

    take_profit, stop_loss = prices

    # --------------------------------------------------------
    # FINAL VALIDATION
    # --------------------------------------------------------

    if side == "long":

        if not (
            take_profit >= market_price + 0.01
        ):

            print(
                f"{symbol} | {strategy} | "
                f"LONG skipped | invalid TP"
            )

            return False

        if not (
            stop_loss <= market_price - 0.01
        ):

            print(
                f"{symbol} | {strategy} | "
                f"LONG skipped | invalid SL"
            )

            return False

        order_side = OrderSide.BUY

    else:

        if not (
            take_profit <= market_price - 0.01
        ):

            print(
                f"{symbol} | {strategy} | "
                f"SHORT skipped | invalid TP"
            )

            return False

        if not (
            stop_loss >= market_price + 0.01
        ):

            print(
                f"{symbol} | {strategy} | "
                f"SHORT skipped | invalid SL"
            )

            return False

        order_side = OrderSide.SELL

    # --------------------------------------------------------
    # ORDER
    # --------------------------------------------------------

    try:

        request = MarketOrderRequest(
            symbol=symbol,
            qty=quantity,
            side=order_side,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(
                limit_price=take_profit,
            ),
            stop_loss=StopLossRequest(
                stop_price=stop_loss,
            ),
        )

        order = TRADING_CLIENT.submit_order(
            order_data=request
        )

        trade = {
            "timestamp": utc_now(),
            "symbol": symbol,
            "strategy": strategy,
            "side": side,
            "quantity": quantity,
            "reference_price": market_price,
            "expected_profit": expected_profit,
            "take_profit": take_profit,
            "stop_loss": stop_loss,
            "order_id": str(order.id),
        }

        with REAL_TRADES_LOCK:

            REAL_TRADES.append(
                trade
            )

            trade_count = len(
                REAL_TRADES
            )

        print(
            f"{symbol} | {strategy} | "
            f"{side.upper()} ORDER SUBMITTED | "
            f"qty={quantity} | "
            f"expected={percent(expected_profit):.2f}% | "
            f"TP={take_profit:.4f} | "
            f"SL={stop_loss:.4f} | "
            f"trade_count={trade_count}"
        )

        return True

    except Exception as exc:

        print(
            f"{symbol} | {strategy} | "
            f"{side.upper()} order failed: {exc}"
        )

        return False


# ============================================================
# LIVE EMA SIGNAL
# ============================================================

def process_live_ema_signal(
    symbol,
    close,
    cross_up,
    cross_down,
):
    if not (
        cross_up
        or cross_down
    ):
        return

    if cross_up:

        side = "long"

    else:

        side = "short"

    expected = get_expected_profit(
        symbol,
        "EMA_10S",
        side,
    )

    print(
        f"{symbol} | 10S EMA | "
        f"{side.upper()} signal | "
        f"expected={percent(expected):.2f}%"
    )

    if expected <= EXPECTED_MINIMUM:

        print(
            f"{symbol} | 10S EMA | "
            f"{side.upper()} skipped | "
            f"expected {percent(expected):.2f}% "
            f"<= {percent(EXPECTED_MINIMUM):.2f}%"
        )

        return

    if symbol_has_exposure(symbol):

        print(
            f"{symbol} | 10S EMA | "
            f"{side.upper()} skipped | "
            f"existing exposure"
        )

        return

    place_bracket_order(
        symbol=symbol,
        side=side,
        market_price=close,
        expected_profit=expected,
        strategy="EMA_10S",
    )


# ============================================================
# LIVE BREAKOUT SIGNAL
# ============================================================

def process_live_breakout_signal(
    symbol,
    previous_high,
    previous_low,
    current_high,
    current_low,
    close,
):
    # --------------------------------------------------------
    # LONG
    # --------------------------------------------------------

    if (
        previous_high is not None
        and current_high > previous_high
    ):

        side = "long"

        expected = get_expected_profit(
            symbol,
            "BREAKOUT_1M",
            side,
        )

        print(
            f"{symbol} | 1M BREAKOUT | "
            f"LONG signal | "
            f"expected={percent(expected):.2f}%"
        )

        if expected <= EXPECTED_MINIMUM:

            print(
                f"{symbol} | 1M BREAKOUT | "
                f"LONG skipped | "
                f"expected {percent(expected):.2f}% "
                f"<= {percent(EXPECTED_MINIMUM):.2f}%"
            )

            return

        if symbol_has_exposure(symbol):
            return

        place_bracket_order(
            symbol=symbol,
            side="long",
            market_price=close,
            expected_profit=expected,
            strategy="BREAKOUT_1M",
        )

    # --------------------------------------------------------
    # SHORT
    # --------------------------------------------------------

    if (
        previous_low is not None
        and current_low < previous_low
    ):

        side = "short"

        expected = get_expected_profit(
            symbol,
            "BREAKOUT_1M",
            side,
        )

        print(
            f"{symbol} | 1M BREAKOUT | "
            f"SHORT signal | "
            f"expected={percent(expected):.2f}%"
        )

        if expected <= EXPECTED_MINIMUM:

            print(
                f"{symbol} | 1M BREAKOUT | "
                f"SHORT skipped | "
                f"expected {percent(expected):.2f}% "
                f"<= {percent(EXPECTED_MINIMUM):.2f}%"
            )

            return

        if symbol_has_exposure(symbol):
            return

        place_bracket_order(
            symbol=symbol,
            side="short",
            market_price=close,
            expected_profit=expected,
            strategy="BREAKOUT_1M",
        )


# ============================================================
# WEBSOCKET PROCESSOR
# ============================================================

def websocket_processing_loop():
    """
    Continuously processes incoming websocket data.

    This loop is intentionally separate from the websocket
    connection itself.
    """

    last_10s_processed = {
        symbol: None
        for symbol in SYMBOLS
    }

    last_1m_processed = {
        symbol: None
        for symbol in SYMBOLS
    }

    while True:

        for symbol in SYMBOLS:

            try:

                # --------------------------------------------
                # UPDATE 10 SECOND DATA
                # --------------------------------------------

                bars_10s = update_10_second_history(
                    symbol
                )

                if (
                    bars_10s is not None
                    and not bars_10s.empty
                ):

                    for timestamp, row in bars_10s.iterrows():

                        if (
                            last_10s_processed[symbol]
                            is not None
                            and timestamp
                            <= last_10s_processed[symbol]
                        ):
                            continue

                        last_10s_processed[symbol] = timestamp

                        (
                            fast,
                            slow,
                            cross_up,
                            cross_down,
                        ) = update_ema_state(
                            symbol,
                            float(row["close"]),
                        )

                        # Historical/backtest statistics
                        # are built from the same incoming
                        # websocket 10-second data.
                        process_ema_history_bar(
                            symbol,
                            timestamp,
                            float(row["high"]),
                            float(row["low"]),
                            float(row["close"]),
                        )

                        # Live signal
                        process_live_ema_signal(
                            symbol,
                            float(row["close"]),
                            cross_up,
                            cross_down,
                        )

                # --------------------------------------------
                # UPDATE 1 MINUTE DATA
                # --------------------------------------------

                bars_1m = update_1_minute_history(
                    symbol
                )

                if (
                    bars_1m is not None
                    and not bars_1m.empty
                ):

                    for timestamp, row in bars_1m.iterrows():

                        if (
                            last_1m_processed[symbol]
                            is not None
                            and timestamp
                            <= last_1m_processed[symbol]
                        ):
                            continue

                        last_1m_processed[symbol] = timestamp

                        state = BREAKOUT_STATE_1M[
                            symbol
                        ]

                        previous_high = (
                            state["previous_high"]
                        )

                        previous_low = (
                            state["previous_low"]
                        )

                        current_high = float(
                            row["high"]
                        )

                        current_low = float(
                            row["low"]
                        )

                        close = float(
                            row["close"]
                        )

                        # Historical/backtest
                        # calculation.
                        process_breakout_history_bar(
                            symbol,
                            timestamp,
                            current_high,
                            current_low,
                        )

                        # Live breakout signal.
                        process_live_breakout_signal(
                            symbol,
                            previous_high,
                            previous_low,
                            current_high,
                            current_low,
                            close,
                        )

            except Exception as exc:

                print(
                    f"{symbol} | processing error: {exc}"
                )

        time.sleep(1)


# ============================================================
# WEBSOCKET
# ============================================================

def websocket_worker():
    """
    Dedicated websocket thread/event loop.
    """

    loop = asyncio.new_event_loop()

    asyncio.set_event_loop(loop)

    stream = StockDataStream(
        API_KEY,
        SECRET_KEY,
        raw_data=False,
        feed=DATA_FEED,
    )

    # Alpaca SDK normally selects the endpoint automatically.
    # For IEX paper/data configurations, explicitly force the
    # IEX websocket endpoint when required.
    if API_KEY.startswith("PK"):

        try:

            stream._endpoint = (
                "wss://stream.data.alpaca.markets/v2/iex"
            )

        except Exception:
            pass

    for symbol in SYMBOLS:

        stream.subscribe_trades(
            on_trade,
            symbol,
        )

    try:

        loop.run_until_complete(
            stream._run_forever()
        )

    except Exception as exc:

        print(
            f"WebSocket stopped: {exc}"
        )

    finally:

        loop.close()


# ============================================================
# DASH
# ============================================================

app = Dash(__name__)

app.layout = html.Div(
    [
        html.H2(
            "Live Trading Dashboard"
        ),

        dcc.Dropdown(
            id="symbol-dropdown",
            options=[
                {
                    "label": symbol,
                    "value": symbol,
                }
                for symbol in SYMBOLS
            ],
            value=SYMBOLS[0],
            clearable=False,
        ),

        dcc.Dropdown(
            id="strategy-dropdown",
            options=[
                {
                    "label": "10S EMA",
                    "value": "EMA_10S",
                },
                {
                    "label": "1M Breakout",
                    "value": "BREAKOUT_1M",
                },
            ],
            value="EMA_10S",
            clearable=False,
        ),

        html.Div(
            id="stats"
        ),

        dcc.Graph(
            id="price-graph"
        ),

        dcc.Interval(
            id="dashboard-update",
            interval=1000,
            n_intervals=0,
        ),
    ]
)


# ============================================================
# DASH CALLBACK
# ============================================================

@app.callback(
    Output(
        "price-graph",
        "figure",
    ),
    Output(
        "stats",
        "children",
    ),
    Input(
        "symbol-dropdown",
        "value",
    ),
    Input(
        "strategy-dropdown",
        "value",
    ),
    Input(
        "dashboard-update",
        "n_intervals",
    ),
)
def update_dashboard(
    symbol,
    strategy,
    n_intervals,
):

    if strategy == "EMA_10S":

        with BARS_10S_LOCK:

            bars = BARS_10S[symbol].copy()

        expected_long = EXPECTED_STATS_10S[
            symbol
        ]["long_average"]

        expected_short = EXPECTED_STATS_10S[
            symbol
        ]["short_average"]

        long_count = len(
            EXPECTED_STATS_10S[symbol][
                "long_profits"
            ]
        )

        short_count = len(
            EXPECTED_STATS_10S[symbol][
                "short_profits"
            ]
        )

    else:

        with BARS_1M_LOCK:

            bars = BARS_1M[symbol].copy()

        expected_long = EXPECTED_STATS_1M[
            symbol
        ]["long_average"]

        expected_short = EXPECTED_STATS_1M[
            symbol
        ]["short_average"]

        long_count = len(
            EXPECTED_STATS_1M[symbol][
                "long_profits"
            ]
        )

        short_count = len(
            EXPECTED_STATS_1M[symbol][
                "short_profits"
            ]
        )

    figure = go.Figure()

    if not bars.empty:

        figure.add_trace(
            go.Candlestick(
                x=bars.index,
                open=bars["open"],
                high=bars["high"],
                low=bars["low"],
                close=bars["close"],
                name=symbol,
            )
        )

    with REAL_TRADES_LOCK:

        trades = [
            trade.copy()
            for trade in REAL_TRADES
            if trade["symbol"] == symbol
            and trade["strategy"] == strategy
        ]

    if trades:

        entry_times = [
            trade["timestamp"]
            for trade in trades
        ]

        entry_prices = [
            trade["reference_price"]
            for trade in trades
        ]

        figure.add_trace(
            go.Scatter(
                x=entry_times,
                y=entry_prices,
                mode="markers",
                marker={
                    "size": 10,
                    "symbol": "triangle-up",
                },
                name="Real Entries",
            )
        )

    figure.update_layout(
        title=f"{symbol} - {strategy}",
        xaxis_title="Time",
        yaxis_title="Price",
        xaxis_rangeslider_visible=False,
    )

    stats = html.Div(
        [
            html.Div(
                f"Long expected max profit: "
                f"{percent(expected_long):.2f}%"
            ),

            html.Div(
                f"Short expected max profit: "
                f"{percent(expected_short):.2f}%"
            ),

            html.Div(
                f"Completed long historical setups: "
                f"{long_count}"
            ),

            html.Div(
                f"Completed short historical setups: "
                f"{short_count}"
            ),

            html.Div(
                f"Real trades: "
                f"{len(trades)}"
            ),
        ]
    )

    return figure, stats


# ============================================================
# START
# ============================================================

def start():
    print(
        "Starting websocket..."
    )

    websocket_thread = threading.Thread(
        target=websocket_worker,
        daemon=True,
    )

    websocket_thread.start()

    print(
        "Starting websocket processing..."
    )

    processing_thread = threading.Thread(
        target=websocket_processing_loop,
        daemon=True,
    )

    processing_thread.start()

    print(
        f"Dashboard running on port {DASH_PORT}"
    )

    app.run(
        debug=False,
        port=DASH_PORT,
    )


if __name__ == "__main__":
    start()