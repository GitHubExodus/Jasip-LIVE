# system_state.py

from datetime import date


# ============================================================
# SYSTEM STATE
# ============================================================

def create_system_state():
    """
    Create the complete runtime state for the trading system.
    """

    return {
        # ----------------------------------------------------
        # Market data
        # ----------------------------------------------------

        "market_data": {},

        "timeframe_data": {
            "5m": {},
            "30m": {},
            "day": {},
            "week": {},
        },

        # ----------------------------------------------------
        # Indicators
        # ----------------------------------------------------

        "indicator_states": {},

        # ----------------------------------------------------
        # Strategies
        # ----------------------------------------------------

        "strategy_states": {},

        # ----------------------------------------------------
        # Methods
        # ----------------------------------------------------

        "methods": {},

        # ----------------------------------------------------
        # Simulator
        # ----------------------------------------------------

        "simulator_states": {},

        # ----------------------------------------------------
        # Equity curves
        # ----------------------------------------------------

        "equity_curves": {},

        # ----------------------------------------------------
        # Contributions
        # ----------------------------------------------------

        "contribution_data": None,

        "contribution_state": {
            "timestamp": None,
            "method_rocs": {},
            "contributions": {},
            "ranked_methods": [],
            "tradable_methods": [],
            "snapshot": None,
        },

        # ----------------------------------------------------
        # Alpaca
        # ----------------------------------------------------

        "alpaca_order_states": {},

        # ----------------------------------------------------
        # Capital
        # ----------------------------------------------------

        "daily_balance": {
            "trading_date": None,
            "starting_balance": None,
        },

        # ----------------------------------------------------
        # Runtime
        # ----------------------------------------------------

        "last_processed_timestamp": None,

        "last_market_bar_timestamp": {},

        "last_strategy_timestamp": {},

        # ----------------------------------------------------
        # System status
        # ----------------------------------------------------

        "initialized": False,
    }


# ============================================================
# MARKET DATA
# ============================================================

def set_market_data(
    state,
    symbol,
    data,
):
    """
    Store market data for one symbol.
    """

    state["market_data"][symbol] = data


def get_market_data(
    state,
    symbol,
):
    """
    Return market data for one symbol.
    """

    return state["market_data"].get(symbol)


# ============================================================
# TIMEFRAME DATA
# ============================================================

def set_timeframe_data(
    state,
    symbol,
    timeframe,
    data,
):
    """
    Store timeframe data for one symbol.
    """

    if timeframe not in state["timeframe_data"]:
        raise ValueError(
            f"Unsupported timeframe: {timeframe}"
        )

    state["timeframe_data"][timeframe][symbol] = data


def get_timeframe_data(
    state,
    symbol,
    timeframe,
):
    """
    Return timeframe data for one symbol.
    """

    if timeframe not in state["timeframe_data"]:
        raise ValueError(
            f"Unsupported timeframe: {timeframe}"
        )

    return state["timeframe_data"][timeframe].get(
        symbol
    )


# ============================================================
# INDICATOR STATE
# ============================================================

def set_indicator_state(
    state,
    symbol,
    timeframe,
    indicator_state,
):
    """
    Store indicator state for one symbol/timeframe.
    """

    key = (
        symbol,
        timeframe,
    )

    state["indicator_states"][key] = (
        indicator_state
    )


def get_indicator_state(
    state,
    symbol,
    timeframe,
):
    """
    Return indicator state for one symbol/timeframe.
    """

    key = (
        symbol,
        timeframe,
    )

    return state["indicator_states"].get(key)


# ============================================================
# STRATEGY STATE
# ============================================================

def set_strategy_state(
    state,
    method_id,
    strategy_state,
):
    """
    Store strategy state for one method.
    """

    state["strategy_states"][method_id] = (
        strategy_state
    )


def get_strategy_state(
    state,
    method_id,
):
    """
    Return strategy state for one method.
    """

    return state["strategy_states"].get(
        method_id
    )


# ============================================================
# METHODS
# ============================================================

def set_method(
    state,
    method,
):
    """
    Store one method.
    """

    state["methods"][method["method_id"]] = method


def set_methods(
    state,
    methods,
):
    """
    Store multiple methods.

    methods may be either:

        list[method]

    or:

        dict[method_id, method]
    """

    if isinstance(methods, dict):

        state["methods"].update(
            methods
        )

        return

    for method in methods:
        set_method(
            state,
            method,
        )


def get_method(
    state,
    method_id,
):
    """
    Return one method.
    """

    return state["methods"].get(
        method_id
    )


# ============================================================
# SIMULATOR STATE
# ============================================================

def set_simulator_state(
    state,
    method_id,
    simulator_state,
):
    """
    Store simulator state for one method.
    """

    state["simulator_states"][method_id] = (
        simulator_state
    )


def get_simulator_state(
    state,
    method_id,
):
    """
    Return simulator state for one method.
    """

    return state["simulator_states"].get(
        method_id
    )


# ============================================================
# EQUITY CURVES
# ============================================================

def set_equity_curve(
    state,
    method_id,
    equity_curve,
):
    """
    Store one method's equity curve.
    """

    state["equity_curves"][method_id] = (
        equity_curve
    )


def get_equity_curve(
    state,
    method_id,
):
    """
    Return one method's equity curve.
    """

    return state["equity_curves"].get(
        method_id
    )


# ============================================================
# CONTRIBUTIONS
# ============================================================

def set_contribution_data(
    state,
    contribution_data,
):
    """
    Store the shared contribution history.
    """

    state["contribution_data"] = (
        contribution_data
    )


def get_contribution_data(state):
    """
    Return shared contribution history.
    """

    return state["contribution_data"]


def set_contribution_state(
    state,
    contribution_state,
):
    """
    Store the latest contribution calculation.
    """

    state["contribution_state"] = (
        contribution_state
    )


def get_contribution_state(state):
    """
    Return latest contribution state.
    """

    return state["contribution_state"]


# ============================================================
# ALPACA ORDER STATES
# ============================================================

def set_alpaca_order_state(
    state,
    method_id,
    order_state,
):
    """
    Store Alpaca order state for one method.
    """

    state["alpaca_order_states"][method_id] = (
        order_state
    )


def get_alpaca_order_state(
    state,
    method_id,
):
    """
    Return Alpaca order state for one method.
    """

    return state["alpaca_order_states"].get(
        method_id
    )


# ============================================================
# DAILY BALANCE
# ============================================================

def set_daily_starting_balance(
    state,
    trading_date,
    starting_balance,
):
    """
    Store the account's starting balance for the day.
    """

    state["daily_balance"]["trading_date"] = (
        trading_date
    )

    state["daily_balance"]["starting_balance"] = (
        float(starting_balance)
    )


def get_daily_starting_balance(state):
    """
    Return the current day's fixed starting balance.
    """

    return state["daily_balance"][
        "starting_balance"
    ]


def get_balance_trading_date(state):
    """
    Return the date associated with the stored
    starting balance.
    """

    return state["daily_balance"][
        "trading_date"
    ]


# ============================================================
# TIMESTAMPS
# ============================================================

def set_last_processed_timestamp(
    state,
    timestamp,
):
    """
    Store the timestamp of the last completely processed tick.
    """

    state["last_processed_timestamp"] = timestamp


def get_last_processed_timestamp(state):
    """
    Return the last completely processed timestamp.
    """

    return state["last_processed_timestamp"]


def set_last_market_bar_timestamp(
    state,
    symbol,
    timestamp,
):
    """
    Store the latest market bar timestamp processed
    for one symbol.
    """

    state["last_market_bar_timestamp"][symbol] = (
        timestamp
    )


def get_last_market_bar_timestamp(
    state,
    symbol,
):
    """
    Return the latest processed market bar timestamp
    for one symbol.
    """

    return state["last_market_bar_timestamp"].get(
        symbol
    )


def set_last_strategy_timestamp(
    state,
    method_id,
    timestamp,
):
    """
    Store the latest timestamp at which a method's strategy
    was recalculated.
    """

    state["last_strategy_timestamp"][method_id] = (
        timestamp
    )


def get_last_strategy_timestamp(
    state,
    method_id,
):
    """
    Return the latest strategy calculation timestamp.
    """

    return state["last_strategy_timestamp"].get(
        method_id
    )


# ============================================================
# SYSTEM STATUS
# ============================================================

def set_initialized(
    state,
    initialized=True,
):
    """
    Set system initialization status.
    """

    state["initialized"] = bool(
        initialized
    )


def is_initialized(state):
    """
    Check whether the system has been initialized.
    """

    return bool(
        state["initialized"]
    )