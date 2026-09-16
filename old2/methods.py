# methods.py

from itertools import product

from old2.config import (
    EMA_PAIRS,
    STRATEGIES,
    STOP_LOSS_MULTIPLIERS,
    RISK_REWARD_RATIOS,
    TIMEFRAMES,
)


# ============================================================
# METHOD ID
# ============================================================

def create_method_id(
    symbol,
    timeframe,
    strategy,
    fast_period,
    slow_period,
    stop_loss_multiplier,
    risk_reward,
):
    """
    Input:
        symbol: stock symbol
        timeframe: timeframe name
        strategy: strategy name
        fast_period: fast EMA period
        slow_period: slow EMA period
        stop_loss_multiplier: stop-loss multiplier
        risk_reward: risk/reward ratio

    Description:
        Creates a unique identifier for a method.

    Output:
        string
    """

    return (
        f"{symbol}_"
        f"{timeframe}_"
        f"{strategy}_"
        f"EMA{fast_period}_{slow_period}_"
        f"SL{stop_loss_multiplier}_"
        f"RR{risk_reward}"
    )


# ============================================================
# CREATE METHOD
# ============================================================

def create_method(
    symbol,
    timeframe,
    strategy,
    fast_period,
    slow_period,
    stop_loss_multiplier,
    risk_reward,
):
    """
    Input:
        symbol: stock symbol
        timeframe: timeframe name
        strategy: strategy name
        fast_period: fast EMA period
        slow_period: slow EMA period
        stop_loss_multiplier: stop-loss multiplier
        risk_reward: risk/reward ratio

    Description:
        Creates the complete configuration for one method.

    Output:
        dictionary
    """

    method_id = create_method_id(
        symbol=symbol,
        timeframe=timeframe,
        strategy=strategy,
        fast_period=fast_period,
        slow_period=slow_period,
        stop_loss_multiplier=stop_loss_multiplier,
        risk_reward=risk_reward,
    )

    return {
        "method_id": method_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "strategy": strategy,
        "fast_period": fast_period,
        "slow_period": slow_period,
        "stop_loss_multiplier": stop_loss_multiplier,
        "risk_reward": risk_reward,
    }


# ============================================================
# GENERATE METHODS FOR ONE STOCK
# ============================================================

def generate_methods_for_stock(symbol):
    """
    Input:
        symbol: stock symbol

    Description:
        Generates every method configuration for one stock.

    Output:
        list of method dictionaries
    """

    methods = []

    for timeframe in TIMEFRAMES:

        for strategy in STRATEGIES:

            # EMA crossover currently has multiple EMA pairs.
            if strategy == "ema_crossover":

                for fast_period, slow_period in EMA_PAIRS:

                    for stop_loss_multiplier in (
                        STOP_LOSS_MULTIPLIERS
                    ):

                        for risk_reward in (
                            RISK_REWARD_RATIOS
                        ):

                            method = create_method(
                                symbol=symbol,
                                timeframe=timeframe,
                                strategy=strategy,
                                fast_period=fast_period,
                                slow_period=slow_period,
                                stop_loss_multiplier=(
                                    stop_loss_multiplier
                                ),
                                risk_reward=risk_reward,
                            )

                            methods.append(method)

            else:

                for stop_loss_multiplier in (
                    STOP_LOSS_MULTIPLIERS
                ):

                    for risk_reward in (
                        RISK_REWARD_RATIOS
                    ):

                        method = create_method(
                            symbol=symbol,
                            timeframe=timeframe,
                            strategy=strategy,
                            fast_period=None,
                            slow_period=None,
                            stop_loss_multiplier=(
                                stop_loss_multiplier
                            ),
                            risk_reward=risk_reward,
                        )

                        methods.append(method)

    return methods


# ============================================================
# GENERATE METHODS FOR MULTIPLE STOCKS
# ============================================================

def generate_all_methods(symbols):
    """
    Input:
        symbols: list of stock symbols

    Description:
        Generates every method for every stock.

    Output:
        list of method dictionaries
    """

    methods = []

    for symbol in symbols:
        methods.extend(
            generate_methods_for_stock(symbol)
        )

    return methods


# ============================================================
# FIND METHOD
# ============================================================

def get_method_by_id(
    methods,
    method_id,
):
    """
    Input:
        methods: list of method dictionaries
        method_id: method identifier

    Description:
        Finds a method using its unique method ID.

    Output:
        method dictionary or None
    """

    for method in methods:

        if method["method_id"] == method_id:
            return method

    return None


# ============================================================
# METHOD COUNT
# ============================================================

def get_method_count_for_stock():
    """
    Input:
        None

    Description:
        Calculates the number of methods generated for one
        stock using the current configuration.

    Output:
        integer
    """

    return (
        len(TIMEFRAMES)
        * len(STRATEGIES)
        * len(EMA_PAIRS)
        * len(STOP_LOSS_MULTIPLIERS)
        * len(RISK_REWARD_RATIOS)
    )