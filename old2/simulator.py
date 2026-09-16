# simulator.py

import numpy as np


# ============================================================
# TRADE CREATION
# ============================================================

def create_pending_trade(
    method_id,
    symbol,
    trade_type,
    entry_price,
    stop_loss_price,
    take_profit_price,
    setup_timestamp,
):
    """
    Create a pending simulated trade.

    The trade is waiting for market price to reach entry_price.
    """

    return {
        "method_id": method_id,
        "symbol": symbol,
        "trade_type": trade_type,

        "status": "pending",

        "entry_price": float(entry_price),
        "stop_loss_price": float(stop_loss_price),
        "take_profit_price": float(take_profit_price),

        "setup_timestamp": setup_timestamp,

        "entry_timestamp": None,
        "exit_timestamp": None,

        "exit_reason": None,
        "exit_price": None,
    }


# ============================================================
# PENDING TRADE
# ============================================================

def update_pending_trade(
    pending_trade,
    entry_price,
    stop_loss_price,
    take_profit_price,
    setup_timestamp,
):
    """
    Replace the existing pending setup with the newest setup.
    """

    pending_trade["entry_price"] = float(entry_price)
    pending_trade["stop_loss_price"] = float(stop_loss_price)
    pending_trade["take_profit_price"] = float(take_profit_price)
    pending_trade["setup_timestamp"] = setup_timestamp

    return pending_trade


def cancel_pending_trade(pending_trade):
    """
    Cancel a pending trade.
    """

    if pending_trade is None:
        return None

    pending_trade["status"] = "cancelled"

    return None


# ============================================================
# ENTRY DETECTION
# ============================================================

def check_long_entry(bar, entry_price):
    """
    Check whether a long entry price was reached.

    Entry occurs when the bar's high reaches the entry price.
    """

    return float(bar["high"]) >= entry_price


def check_short_entry(bar, entry_price):
    """
    Check whether a short entry price was reached.

    Entry occurs when the bar's low reaches the entry price.
    """

    return float(bar["low"]) <= entry_price


def check_entry(bar, trade_type, entry_price):
    """
    Check whether a pending trade should enter.
    """

    if trade_type == "long":
        return check_long_entry(bar, entry_price)

    if trade_type == "short":
        return check_short_entry(bar, entry_price)

    raise ValueError(f"Unsupported trade type: {trade_type}")


# ============================================================
# ACTIVATE TRADE
# ============================================================

def activate_trade(pending_trade, entry_timestamp):
    """
    Convert a pending trade into an active trade.
    """

    pending_trade["status"] = "active"
    pending_trade["entry_timestamp"] = entry_timestamp

    return pending_trade


# ============================================================
# ACTIVE TRADE
# ============================================================

def check_long_exit(bar, stop_loss_price, take_profit_price):
    """
    Check SL/TP for a long trade.

    If both SL and TP are reached during the same candle,
    stop loss wins.
    """

    low = float(bar["low"])
    high = float(bar["high"])

    if low <= stop_loss_price:
        return "stop_loss", stop_loss_price

    if high >= take_profit_price:
        return "take_profit", take_profit_price

    return None, None


def check_short_exit(bar, stop_loss_price, take_profit_price):
    """
    Check SL/TP for a short trade.

    If both SL and TP are reached during the same candle,
    stop loss wins.
    """

    low = float(bar["low"])
    high = float(bar["high"])

    if high >= stop_loss_price:
        return "stop_loss", stop_loss_price

    if low <= take_profit_price:
        return "take_profit", take_profit_price

    return None, None


def check_trade_exit(bar, trade_type, stop_loss_price, take_profit_price):
    """
    Check whether an active trade has completed.
    """

    if trade_type == "long":
        return check_long_exit(
            bar,
            stop_loss_price,
            take_profit_price,
        )

    if trade_type == "short":
        return check_short_exit(
            bar,
            stop_loss_price,
            take_profit_price,
        )

    raise ValueError(f"Unsupported trade type: {trade_type}")


# ============================================================
# COMPLETE TRADE
# ============================================================

def complete_trade(
    trade,
    exit_timestamp,
    exit_reason,
    exit_price,
):
    """
    Complete an active trade.
    """

    trade["status"] = "completed"

    trade["exit_timestamp"] = exit_timestamp
    trade["exit_reason"] = exit_reason
    trade["exit_price"] = float(exit_price)

    return trade


# ============================================================
# TRADE RETURN
# ============================================================

def calculate_trade_return(entry_price, exit_price, trade_type):
    """
    Calculate percentage return for a completed trade.
    """

    if entry_price <= 0:
        return np.nan

    if trade_type == "long":
        return ((exit_price - entry_price) / entry_price) * 100.0

    if trade_type == "short":
        return ((entry_price - exit_price) / entry_price) * 100.0

    raise ValueError(f"Unsupported trade type: {trade_type}")


def add_trade_return(trade):
    """
    Add percentage return to a completed trade.
    """

    if trade["status"] != "completed":
        return trade

    trade["return_percent"] = calculate_trade_return(
        trade["entry_price"],
        trade["exit_price"],
        trade["trade_type"],
    )

    return trade


# ============================================================
# PROCESS PENDING TRADE
# ============================================================

def process_pending_trade(
    pending_trade,
    bar,
    bar_timestamp,
):
    """
    Process one pending trade against a new market bar.

    Returns:
        trade, completed_trade

    If entry occurs, the pending trade becomes active.

    If the newly entered trade also hits SL/TP on the same
    candle, the trade is completed immediately.

    SL wins if both SL and TP are touched on the same candle.
    """

    if pending_trade is None:
        return None, None

    if pending_trade["status"] != "pending":
        return pending_trade, None

    entered = check_entry(
        bar,
        pending_trade["trade_type"],
        pending_trade["entry_price"],
    )

    if not entered:
        return pending_trade, None

    trade = activate_trade(
        pending_trade,
        bar_timestamp,
    )

    exit_reason, exit_price = check_trade_exit(
        bar,
        trade["trade_type"],
        trade["stop_loss_price"],
        trade["take_profit_price"],
    )

    if exit_reason is None:
        return trade, None

    trade = complete_trade(
        trade,
        bar_timestamp,
        exit_reason,
        exit_price,
    )

    trade = add_trade_return(trade)

    return None, trade


# ============================================================
# PROCESS ACTIVE TRADE
# ============================================================

def process_active_trade(
    active_trade,
    bar,
    bar_timestamp,
):
    """
    Process one active trade against a new market bar.
    """

    if active_trade is None:
        return None, None

    if active_trade["status"] != "active":
        return active_trade, None

    exit_reason, exit_price = check_trade_exit(
        bar,
        active_trade["trade_type"],
        active_trade["stop_loss_price"],
        active_trade["take_profit_price"],
    )

    if exit_reason is None:
        return active_trade, None

    active_trade = complete_trade(
        active_trade,
        bar_timestamp,
        exit_reason,
        exit_price,
    )

    active_trade = add_trade_return(active_trade)

    return None, active_trade


# ============================================================
# PROCESS ONE METHOD
# ============================================================

def process_method_trade(
    method_state,
    bar,
    bar_timestamp,
    new_trade_setup=None,
):
    """
    Process one method for one new market bar.

    method_state contains:

        pending_trade
        active_trade
        completed_trades

    new_trade_setup is either None or:

        {
            "entry_price": ...,
            "stop_loss_price": ...,
            "take_profit_price": ...,
            "trade_type": ...,
            "setup_timestamp": ...
        }

    Rules:

    1. Existing active trade has priority.
    2. An active trade cannot create another trade.
    3. Existing pending entry can be replaced by a new setup.
    4. A pending entry is tested against the current market bar.
    5. Completed trades are returned.
    """

    completed_trade = None

    # --------------------------------------------------------
    # ACTIVE TRADE
    # --------------------------------------------------------

    if method_state["active_trade"] is not None:

        (
            method_state["active_trade"],
            completed_trade,
        ) = process_active_trade(
            method_state["active_trade"],
            bar,
            bar_timestamp,
        )

        if completed_trade is not None:
            method_state["completed_trades"].append(
                completed_trade
            )

        # Never create another trade while the old trade
        # was active during this bar.
        return method_state, completed_trade

    # --------------------------------------------------------
    # NEW SETUP
    # --------------------------------------------------------

    if new_trade_setup is not None:

        method_state["pending_trade"] = create_pending_trade(
            method_id=method_state["method_id"],
            symbol=method_state["symbol"],
            trade_type=new_trade_setup["trade_type"],
            entry_price=new_trade_setup["entry_price"],
            stop_loss_price=new_trade_setup["stop_loss_price"],
            take_profit_price=new_trade_setup["take_profit_price"],
            setup_timestamp=new_trade_setup["setup_timestamp"],
        )

    # --------------------------------------------------------
    # PENDING TRADE
    # --------------------------------------------------------

    if method_state["pending_trade"] is not None:

        (
            method_state["pending_trade"],
            completed_trade,
        ) = process_pending_trade(
            method_state["pending_trade"],
            bar,
            bar_timestamp,
        )

        if completed_trade is not None:
            method_state["completed_trades"].append(
                completed_trade
            )

    return method_state, completed_trade


# ============================================================
# CREATE METHOD SIMULATOR STATE
# ============================================================

def create_method_simulator_state(
    method_id,
    symbol,
):
    """
    Create runtime trade state for one method.
    """

    return {
        "method_id": method_id,
        "symbol": symbol,

        "pending_trade": None,
        "active_trade": None,

        "completed_trades": [],
    }


# ============================================================
# GET ACTIVE TRADE
# ============================================================

def get_active_trade(method_state):
    """
    Return the active trade for a method.
    """

    return method_state["active_trade"]


# ============================================================
# GET PENDING TRADE
# ============================================================

def get_pending_trade(method_state):
    """
    Return the pending trade for a method.
    """

    return method_state["pending_trade"]


# ============================================================
# GET COMPLETED TRADES
# ============================================================

def get_completed_trades(method_state):
    """
    Return all completed trades for a method.
    """

    return method_state["completed_trades"]