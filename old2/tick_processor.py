# tick_processor.py

from datetime import datetime

from old2.config import (
    TIMEFRAMES,
    ENTRY_RANGE_MULTIPLIER,
    MAX_TRADABLE_METHODS,
    R2_PATHS,
)

from old2.market_data import get_calculation_bar
from old2.timeframe_data import update_all_timeframes
from old2.indicator_state import update_indicator_state, get_indicator_value
from old2.strategies import calculate_strategy
from old2.trade_levels import calculate_trade_setup
from old2.simulator import (
    process_method_trade,
    get_active_trade,
    get_pending_trade,
)
from old2.equity_curves import (
    update_equity_curve,
    equity_curves_to_dataframe,
)
from old2.contributions import calculate_contribution_state
from old2.capital_allocation import calculate_method_allocation

from old2.alpaca_trading import (
    get_daily_starting_balance,
    cancel_method_entry,
    submit_method_bracket_trade,
    get_position,
)


# ============================================================
# MARKET DATA
# ============================================================

def update_symbol_market_data(state, symbol, new_5m_data):
    """
    Add newly received 5m data to the symbol's market data.

    Returns:
        Updated 5m dataframe.
    """

    from old2.market_data import append_new_5m_data

    old_data = state["market_data"].get(symbol)

    if old_data is None:
        updated_data = new_5m_data.copy()
    else:
        updated_data = append_new_5m_data(
            old_data,
            new_5m_data,
        )

    state["market_data"][symbol] = updated_data

    return updated_data


# ============================================================
# TIMEFRAMES
# ============================================================

def update_symbol_timeframes(state, symbol, data_5m):
    """
    Update 5m, 30m, day, and week data for one symbol.
    """

    existing = {
        "30m": state["timeframe_data"]["30m"].get(symbol),
        "day": state["timeframe_data"]["day"].get(symbol),
        "week": state["timeframe_data"]["week"].get(symbol),
    }

    (
        data_5m,
        data_30m,
        data_day,
        data_week,
    ) = update_all_timeframes(
        data_5m,
        existing["30m"],
        existing["day"],
        existing["week"],
    )

    state["timeframe_data"]["5m"][symbol] = data_5m
    state["timeframe_data"]["30m"][symbol] = data_30m
    state["timeframe_data"]["day"][symbol] = data_day
    state["timeframe_data"]["week"][symbol] = data_week

    return {
        "5m": data_5m,
        "30m": data_30m,
        "day": data_day,
        "week": data_week,
    }


# ============================================================
# INDICATORS
# ============================================================

def update_symbol_indicators(state, symbol, timeframe_data):
    """
    Update indicator state for every timeframe.

    Indicator calculations remain inside indicator_state.py.
    """

    symbol_states = state["indicator_states"].setdefault(
        symbol,
        {},
    )

    for timeframe, data in timeframe_data.items():

        if data is None or len(data) == 0:
            continue

        existing_state = symbol_states.get(timeframe)

        if existing_state is None:
            # Initial calculation.
            from old2.indicator_state import initialize_indicator_state

            symbol_states[timeframe] = initialize_indicator_state(
                data
            )

        else:
            symbol_states[timeframe] = update_indicator_state(
                existing_state,
                data,
            )

    return symbol_states


# ============================================================
# STRATEGIES
# ============================================================

def update_symbol_strategies(
    state,
    symbol,
    timeframe_data,
):
    """
    Calculate strategies using the delayed calculation bar.

    The newest market bar is never used for strategy calculation.
    """

    symbol_indicator_states = state["indicator_states"].get(
        symbol,
        {},
    )

    symbol_strategy_states = state["strategy_states"].setdefault(
        symbol,
        {},
    )

    for timeframe in TIMEFRAMES:

        indicator_state = symbol_indicator_states.get(timeframe)

        if indicator_state is None:
            continue

        data = timeframe_data.get(timeframe)

        if data is None or len(data) < 2:
            continue

        # Explicitly identify the delayed calculation bar.
        calculation_bar = get_calculation_bar(data)

        if calculation_bar is None:
            continue

        calculation_timestamp = calculation_bar["timestamp"]

        previous_timestamp = state["last_strategy_timestamp"].get(
            (symbol, timeframe)
        )

        # Only recalculate when this timeframe has advanced.
        if previous_timestamp == calculation_timestamp:
            continue

        strategy_state = calculate_strategy(
            "ema_crossover",
            indicator_state,
        )

        symbol_strategy_states[timeframe] = {
            "timestamp": calculation_timestamp,
            "state": strategy_state,
        }

        state["last_strategy_timestamp"][
            (symbol, timeframe)
        ] = calculation_timestamp

    return symbol_strategy_states


# ============================================================
# DAILY BALANCE
# ============================================================

def ensure_daily_starting_balance(
    state,
    trading_client,
    current_timestamp,
):
    """
    Get Alpaca's account balance once at the beginning
    of each trading day.
    """

    trading_date = current_timestamp.date()

    if state["daily_balance"]["trading_date"] == trading_date:
        return state["daily_balance"]["starting_balance"]

    starting_balance = get_daily_starting_balance(
        trading_client
    )

    state["daily_balance"] = {
        "trading_date": trading_date,
        "starting_balance": starting_balance,
    }

    return starting_balance


# ============================================================
# ALPACA PENDING ENTRY
# ============================================================

def cancel_previous_method_entry(
    state,
    trading_client,
    method_id,
):
    """
    Cancel the previous pending Alpaca entry for this method.

    If there is no stored pending order, no API call is needed.
    """

    order_state = state["alpaca_order_states"].get(method_id)

    if order_state is None:
        return

    entry_order_id = order_state.get("entry_order_id")

    if entry_order_id is None:
        return

    cancel_method_entry(
        trading_client,
        method_id,
        order_state,
    )

    order_state["entry_order_id"] = None


# ============================================================
# METHOD PROCESSING
# ============================================================

def process_method(
    state,
    method,
    symbol,
    newest_market_bar,
    timeframe_data,
    trading_client,
    starting_balance,
):
    """
    Process one complete method.

    A method is:

        stock
        × timeframe
        × strategy
        × EMA pair
        × SL multiplier
        × RR
    """

    method_id = method["method_id"]
    timeframe = method["timeframe"]
    strategy_name = method["strategy"]

    # --------------------------------------------------------
    # 1. Cancel previous pending Alpaca entry
    # --------------------------------------------------------

    cancel_previous_method_entry(
        state,
        trading_client,
        method_id,
    )

    # --------------------------------------------------------
    # 2. Get simulator state
    # --------------------------------------------------------

    simulator_state = state["simulator_states"][method_id]

    active_trade = get_active_trade(simulator_state)

    # If a simulated trade is active, do not create another one.
    has_active_trade = active_trade is not None

    # --------------------------------------------------------
    # 3. Get delayed strategy state
    # --------------------------------------------------------

    strategy_data = (
        state["strategy_states"]
        .get(symbol, {})
        .get(timeframe)
    )

    if strategy_data is None:
        return None

    strategy_state = strategy_data["state"]

    fast_period = method["fast_period"]
    slow_period = method["slow_period"]

    pair_strategy = strategy_state.get(
        (fast_period, slow_period)
    )

    if pair_strategy is None:
        return None

    # --------------------------------------------------------
    # 4. Get indicator state
    # --------------------------------------------------------

    indicator_state = (
        state["indicator_states"]
        .get(symbol, {})
        .get(timeframe)
    )

    if indicator_state is None:
        return None

    green_average = get_indicator_value(
        indicator_state,
        "green_average",
    )

    red_average = get_indicator_value(
        indicator_state,
        "red_average",
    )

    # --------------------------------------------------------
    # 5. Calculate entry price
    # --------------------------------------------------------

    entry_price = pair_strategy.get("crossover_price")

    if entry_price is None:
        return None

    # Current actual market price comes from newest bar.
    current_price = newest_market_bar["close"]

    # --------------------------------------------------------
    # 6. Calculate trade setup
    # --------------------------------------------------------

    setup = calculate_trade_setup(
        entry_price=entry_price,
        current_price=current_price,
        green_average=green_average,
        red_average=red_average,
        stop_loss_multiplier=method[
            "stop_loss_multiplier"
        ],
        risk_reward=method["risk_reward"],
    )

    if setup is None:
        return None

    # --------------------------------------------------------
    # 7. Simulator
    # --------------------------------------------------------

    # The simulator sees the newest market bar.
    #
    # If an active trade exists, it only processes that trade.
    # Otherwise, it can create/replace a pending setup.

    completed_trade = process_method_trade(
        simulator_state,
        newest_market_bar,
        setup,
    )

    if completed_trade is not None:

        handle_completed_trade(
            state,
            completed_trade,
        )

    # --------------------------------------------------------
    # 8. Actual trade prevents new entry
    # --------------------------------------------------------

    if has_active_trade:
        return {
            "method_id": method_id,
            "status": "active_trade",
        }

    # --------------------------------------------------------
    # 9. Check entry eligibility
    # --------------------------------------------------------

    if not setup["entry_eligible"]:
        return {
            "method_id": method_id,
            "status": "entry_not_eligible",
        }

    # --------------------------------------------------------
    # 10. Check whether method is tradable
    # --------------------------------------------------------

    contribution_state = state["contribution_state"]

    if not method_is_currently_tradable(
        contribution_state,
        method_id,
    ):
        return {
            "method_id": method_id,
            "status": "not_tradable",
        }

    # --------------------------------------------------------
    # 11. Calculate capital allocation
    # --------------------------------------------------------

    allocation = calculate_method_allocation(
        starting_balance=starting_balance,
        method=method,
        entry_price=entry_price,
    )

    if allocation is None:
        return {
            "method_id": method_id,
            "status": "allocation_failed",
        }

    if allocation["share_quantity"] <= 0:
        return {
            "method_id": method_id,
            "status": "zero_shares",
        }

    # --------------------------------------------------------
    # 12. Submit Alpaca entry + SL + TP
    # --------------------------------------------------------

    order_state = submit_method_bracket_trade(
        trading_client=trading_client,
        method=method,
        allocation=allocation,
        setup=setup,
    )

    state["alpaca_order_states"][method_id] = order_state

    return {
        "method_id": method_id,
        "status": "entry_submitted",
        "setup": setup,
        "allocation": allocation,
        "order_state": order_state,
    }


# ============================================================
# TRADABLE CHECK
# ============================================================

def method_is_currently_tradable(
    contribution_state,
    method_id,
):
    """
    A method may trade only if:

        1. ROC > 0
        2. It is inside the current top-20 ranking
    """

    if contribution_state is None:
        return False

    method_rocs = contribution_state.get(
        "method_rocs",
        {},
    )

    roc = method_rocs.get(method_id)

    if roc is None or roc <= 0:
        return False

    tradable_methods = contribution_state.get(
        "tradable_methods",
        [],
    )

    return method_id in tradable_methods


# ============================================================
# COMPLETED SIMULATED TRADE
# ============================================================

def handle_completed_trade(
    state,
    completed_trade,
):
    """
    Add the completed trade to the method equity curve.

    The updated curve remains in memory.

    R2 persistence is deliberately NOT done here individually.
    The caller batches persistence after all methods finish.
    """

    method_id = completed_trade["method_id"]

    equity_curve = state["equity_curves"].get(method_id)

    if equity_curve is None:
        return

    state["equity_curves"][method_id] = update_equity_curve(
        equity_curve,
        completed_trade,
    )


# ============================================================
# CONTRIBUTIONS
# ============================================================

def refresh_contribution_state(
    state,
    timestamp,
):
    """
    Recalculate all method ROC values, contributions,
    rankings, and top-20 tradable methods.
    """

    contribution_state = calculate_contribution_state(
        state["equity_curves"],
        timestamp=timestamp,
        max_tradable_methods=MAX_TRADABLE_METHODS,
    )

    state["contribution_state"] = contribution_state

    return contribution_state


# ============================================================
# BATCH PERSISTENCE
# ============================================================

def persist_updated_equity_curves(state):
    """
    Save ALL equity curves as one shared Parquet dataset.

    Called once per tick if anything changed.
    """

    equity_data = equity_curves_to_dataframe(
        state["equity_curves"]
    )

    if equity_data.empty:
        return

    from old2.data_storage import save_parquet

    save_parquet(
        equity_data,
        R2_PATHS["equity_curves"],
    )


def persist_contributions(state):
    """
    Save the shared contribution history.
    """

    contribution_data = state.get(
        "contribution_data"
    )

    if contribution_data is None:
        return

    if contribution_data.empty:
        return

    from old2.data_storage import save_parquet

    save_parquet(
        contribution_data,
        R2_PATHS["contributions"],
    )


# ============================================================
# ONE SYMBOL TICK
# ============================================================

def process_symbol_tick(
    state,
    symbol,
    new_5m_data,
    trading_client,
):
    """
    Process one newly received 5m update for one stock.
    """

    # --------------------------------------------------------
    # 1. Market data
    # --------------------------------------------------------

    data_5m = update_symbol_market_data(
        state,
        symbol,
        new_5m_data,
    )

    if len(data_5m) < 2:
        return []

    newest_market_bar = data_5m.iloc[-1]

    newest_timestamp = newest_market_bar["timestamp"]

    # Prevent processing the same market bar twice.
    previous_timestamp = state["last_market_bar_timestamp"].get(
        symbol
    )

    if previous_timestamp == newest_timestamp:
        return []

    state["last_market_bar_timestamp"][symbol] = (
        newest_timestamp
    )

    # --------------------------------------------------------
    # 2. Timeframes
    # --------------------------------------------------------

    timeframe_data = update_symbol_timeframes(
        state,
        symbol,
        data_5m,
    )

    # --------------------------------------------------------
    # 3. Indicators
    # --------------------------------------------------------

    update_symbol_indicators(
        state,
        symbol,
        timeframe_data,
    )

    # --------------------------------------------------------
    # 4. Strategies
    # --------------------------------------------------------

    update_symbol_strategies(
        state,
        symbol,
        timeframe_data,
    )

    # --------------------------------------------------------
    # 5. Daily account balance
    # --------------------------------------------------------

    starting_balance = ensure_daily_starting_balance(
        state,
        trading_client,
        newest_timestamp,
    )

    # --------------------------------------------------------
    # 6. Process methods
    # --------------------------------------------------------

    results = []

    methods = [
        method
        for method in state["methods"].values()
        if method["symbol"] == symbol
    ]

    for method in methods:

        result = process_method(
            state=state,
            method=method,
            symbol=symbol,
            newest_market_bar=newest_market_bar,
            timeframe_data=timeframe_data,
            trading_client=trading_client,
            starting_balance=starting_balance,
        )

        if result is not None:
            results.append(result)

    # --------------------------------------------------------
    # 7. Refresh contributions
    # --------------------------------------------------------

    # Contributions are recalculated after all completed
    # trades from this tick have been processed.

    contribution_state = refresh_contribution_state(
        state,
        newest_timestamp,
    )

    state["contribution_state"] = contribution_state

    # --------------------------------------------------------
    # 8. Persist shared state
    # --------------------------------------------------------

    persist_updated_equity_curves(state)

    persist_contributions(state)

    # --------------------------------------------------------
    # 9. Global timestamp
    # --------------------------------------------------------

    state["last_processed_timestamp"] = newest_timestamp

    return results


# ============================================================
# GENERIC TICK ENTRY POINT
# ============================================================

def process_tick(
    state,
    symbol,
    new_5m_data,
    trading_client,
):
    """
    Public entry point.

    The rest of the system only needs to call this function
    whenever a new completed 5m bar is available.
    """

    return process_symbol_tick(
        state=state,
        symbol=symbol,
        new_5m_data=new_5m_data,
        trading_client=trading_client,
    )