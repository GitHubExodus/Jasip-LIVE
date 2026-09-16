# alpaca_trading.py

import os
import math

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    LimitOrderRequest,
    TakeProfitRequest,
    StopLossRequest,
)
from alpaca.trading.enums import (
    OrderSide,
    TimeInForce,
    OrderClass,
)


# ============================================================
# CLIENT
# ============================================================

def create_trading_client(
    api_key=None,
    secret_key=None,
    paper=True,
):
    """
    Create an Alpaca trading client.

    If credentials are not supplied, environment variables
    are used.
    """

    if api_key is None:
        api_key = os.getenv("ALPACA_API_KEY")

    if secret_key is None:
        secret_key = os.getenv("ALPACA_SECRET_KEY")

    if not api_key:
        raise ValueError(
            "ALPACA_API_KEY is not set"
        )

    if not secret_key:
        raise ValueError(
            "ALPACA_SECRET_KEY is not set"
        )

    return TradingClient(
        api_key=api_key,
        secret_key=secret_key,
        paper=paper,
    )


# ============================================================
# ACCOUNT
# ============================================================

def get_account(client):
    """
    Get the current Alpaca account.
    """

    return client.get_account()


def get_total_cash(client):
    """
    Return current account cash.
    """

    account = get_account(client)

    return float(account.cash)


def get_account_equity(client):
    """
    Return current account equity.
    """

    account = get_account(client)

    return float(account.equity)


def get_buying_power(client):
    """
    Return current account buying power.
    """

    account = get_account(client)

    return float(account.buying_power)


# ============================================================
# DAILY STARTING BALANCE
# ============================================================

def get_daily_starting_balance(client):
    """
    Get the account balance used as the starting balance
    for the trading day.

    This should be called once at the beginning of each
    trading day and then stored in system state.
    """

    account = get_account(client)

    return float(account.equity)


# ============================================================
# POSITIONS
# ============================================================

def get_positions(client):
    """
    Get all currently open Alpaca positions.
    """

    return client.get_all_positions()


def get_position(client, symbol):
    """
    Get a position for one symbol.

    Returns None if no position exists.
    """

    positions = get_positions(client)

    for position in positions:

        if position.symbol == symbol:
            return position

    return None


def has_position(client, symbol):
    """
    Check whether Alpaca currently has an open position
    for a symbol.
    """

    return get_position(client, symbol) is not None


# ============================================================
# OPEN ORDERS
# ============================================================

def get_open_orders(client):
    """
    Get all currently open orders.
    """

    return client.get_orders()


def get_open_orders_for_symbol(client, symbol):
    """
    Get all open orders for one symbol.
    """

    orders = get_open_orders(client)

    return [
        order
        for order in orders
        if order.symbol == symbol
    ]


# ============================================================
# CANCEL ORDERS
# ============================================================

def cancel_order(client, order_id):
    """
    Cancel one Alpaca order.
    """

    client.cancel_order_by_id(order_id)


def cancel_all_orders(client):
    """
    Cancel every open Alpaca order.
    """

    client.cancel_orders()


def cancel_orders_for_symbol(client, symbol):
    """
    Cancel all open orders for one symbol.
    """

    orders = get_open_orders_for_symbol(
        client,
        symbol,
    )

    for order in orders:
        cancel_order(
            client,
            order.id,
        )


# ============================================================
# CANCEL METHOD ENTRY
# ============================================================

def cancel_pending_entry_order(
    client,
    order_id,
):
    """
    Cancel a method's currently pending entry order.

    The tick processor should call this on every tick before
    replacing the method's entry setup.
    """

    if order_id is None:
        return

    try:
        cancel_order(
            client,
            order_id,
        )
    except Exception:
        # The order may already have filled, been cancelled,
        # or otherwise left the open-order state.
        pass


# ============================================================
# ENTRY ORDER
# ============================================================

def submit_long_entry_order(
    client,
    symbol,
    quantity,
    entry_price,
):
    """
    Submit a long limit entry order.

    The entry price is the strategy's calculated crossover
    price.
    """

    quantity = int(quantity)

    if quantity <= 0:
        return None

    entry_price = float(entry_price)

    if entry_price <= 0:
        return None

    request = LimitOrderRequest(
        symbol=symbol,
        qty=quantity,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
        limit_price=entry_price,
    )

    return client.submit_order(
        order_data=request
    )


def submit_short_entry_order(
    client,
    symbol,
    quantity,
    entry_price,
):
    """
    Submit a short limit entry order.
    """

    quantity = int(quantity)

    if quantity <= 0:
        return None

    entry_price = float(entry_price)

    if entry_price <= 0:
        return None

    request = LimitOrderRequest(
        symbol=symbol,
        qty=quantity,
        side=OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
        limit_price=entry_price,
    )

    return client.submit_order(
        order_data=request
    )


def submit_entry_order(
    client,
    symbol,
    quantity,
    entry_price,
    trade_type="long",
):
    """
    Submit an entry order for the requested trade type.
    """

    if trade_type == "long":
        return submit_long_entry_order(
            client,
            symbol,
            quantity,
            entry_price,
        )

    if trade_type == "short":
        return submit_short_entry_order(
            client,
            symbol,
            quantity,
            entry_price,
        )

    raise ValueError(
        f"Unsupported trade type: {trade_type}"
    )


# ============================================================
# BRACKET ORDER
# ============================================================

def submit_long_bracket_order(
    client,
    symbol,
    quantity,
    entry_price,
    stop_loss_price,
    take_profit_price,
):
    """
    Submit a long bracket order.

    Once the entry fills, Alpaca manages the SL and TP as
    attached exit orders.
    """

    quantity = int(quantity)

    if quantity <= 0:
        return None

    request = LimitOrderRequest(
        symbol=symbol,
        qty=quantity,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
        limit_price=float(entry_price),
        order_class=OrderClass.BRACKET,
        take_profit=TakeProfitRequest(
            limit_price=float(take_profit_price),
        ),
        stop_loss=StopLossRequest(
            stop_price=float(stop_loss_price),
        ),
    )

    return client.submit_order(
        order_data=request
    )


def submit_short_bracket_order(
    client,
    symbol,
    quantity,
    entry_price,
    stop_loss_price,
    take_profit_price,
):
    """
    Submit a short bracket order.
    """

    quantity = int(quantity)

    if quantity <= 0:
        return None

    request = LimitOrderRequest(
        symbol=symbol,
        qty=quantity,
        side=OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
        limit_price=float(entry_price),
        order_class=OrderClass.BRACKET,
        take_profit=TakeProfitRequest(
            limit_price=float(take_profit_price),
        ),
        stop_loss=StopLossRequest(
            stop_price=float(stop_loss_price),
        ),
    )

    return client.submit_order(
        order_data=request
    )


def submit_bracket_order(
    client,
    symbol,
    quantity,
    entry_price,
    stop_loss_price,
    take_profit_price,
    trade_type="long",
):
    """
    Submit a complete entry + SL + TP bracket.
    """

    if trade_type == "long":

        return submit_long_bracket_order(
            client,
            symbol,
            quantity,
            entry_price,
            stop_loss_price,
            take_profit_price,
        )

    if trade_type == "short":

        return submit_short_bracket_order(
            client,
            symbol,
            quantity,
            entry_price,
            stop_loss_price,
            take_profit_price,
        )

    raise ValueError(
        f"Unsupported trade type: {trade_type}"
    )


# ============================================================
# ORDER STATUS
# ============================================================

def get_order(client, order_id):
    """
    Get one order by ID.
    """

    return client.get_order_by_id(order_id)


def get_order_status(client, order_id):
    """
    Return the status of one order.
    """

    order = get_order(
        client,
        order_id,
    )

    return str(order.status)


def is_order_filled(client, order_id):
    """
    Check whether an order has filled.
    """

    return get_order_status(
        client,
        order_id,
    ).lower() == "filled"


def is_order_active(client, order_id):
    """
    Check whether an order is still active.
    """

    status = get_order_status(
        client,
        order_id,
    ).lower()

    return status in {
        "new",
        "accepted",
        "pending_new",
        "partially_filled",
    }


# ============================================================
# FILLED ORDER INFORMATION
# ============================================================

def get_filled_quantity(client, order_id):
    """
    Return the quantity filled by an order.
    """

    order = get_order(
        client,
        order_id,
    )

    if order.filled_qty is None:
        return 0

    return int(
        float(order.filled_qty)
    )


def get_average_fill_price(client, order_id):
    """
    Return the average fill price.
    """

    order = get_order(
        client,
        order_id,
    )

    if order.filled_avg_price is None:
        return None

    return float(
        order.filled_avg_price
    )


# ============================================================
# METHOD ORDER STATE
# ============================================================

def create_method_order_state(method_id):
    """
    Runtime Alpaca order state for one method.
    """

    return {
        "method_id": method_id,

        "entry_order_id": None,

        "entry_status": None,

        "quantity": 0,

        "entry_price": None,

        "stop_loss_price": None,

        "take_profit_price": None,

        "trade_type": None,

        "active": False,
    }


def clear_method_order_state(state):
    """
    Clear Alpaca order state after a method's trade is finished.
    """

    method_id = state["method_id"]

    state.clear()

    state.update(
        create_method_order_state(
            method_id
        )
    )

    return state


# ============================================================
# SUBMIT METHOD TRADE
# ============================================================

def submit_method_bracket_trade(
    client,
    method_state,
    symbol,
    quantity,
    entry_price,
    stop_loss_price,
    take_profit_price,
    trade_type="long",
):
    """
    Submit one method's Alpaca bracket order and update its
    runtime order state.
    """

    order = submit_bracket_order(
        client=client,
        symbol=symbol,
        quantity=quantity,
        entry_price=entry_price,
        stop_loss_price=stop_loss_price,
        take_profit_price=take_profit_price,
        trade_type=trade_type,
    )

    if order is None:
        return None

    method_state["entry_order_id"] = str(
        order.id
    )

    method_state["entry_status"] = str(
        order.status
    )

    method_state["quantity"] = int(
        quantity
    )

    method_state["entry_price"] = float(
        entry_price
    )

    method_state["stop_loss_price"] = float(
        stop_loss_price
    )

    method_state["take_profit_price"] = float(
        take_profit_price
    )

    method_state["trade_type"] = trade_type

    method_state["active"] = True

    return order


# ============================================================
# CANCEL METHOD TRADE
# ============================================================

def cancel_method_entry(
    client,
    method_state,
):
    """
    Cancel the current pending entry for a method.

    The tick processor can then create a new entry setup.
    """

    order_id = method_state.get(
        "entry_order_id"
    )

    if order_id is None:
        return

    cancel_pending_entry_order(
        client,
        order_id,
    )

    method_state["entry_order_id"] = None
    method_state["entry_status"] = None


# ============================================================
# CLOSE POSITION
# ============================================================

def close_symbol_position(
    client,
    symbol,
):
    """
    Close an existing position for a symbol.
    """

    position = get_position(
        client,
        symbol,
    )

    if position is None:
        return None

    return client.close_position(
        symbol
    )