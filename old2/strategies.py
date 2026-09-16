# strategies.py

import numpy as np

from old2.config import EMA_PAIRS

from old2.strategy_calculations import (
    calculate_ema_crossover_price,
    get_ema_crossover_direction,
)


# ============================================================
# EMA CROSSOVER STRATEGY
# ============================================================

def calculate_ema_crossover_strategy(
    indicator_state,
):
    """
    Input:
        indicator_state: current indicator state for a
                         stock and timeframe

    Description:
        Calculates the required price for the fast EMA to
        cross above the slow EMA for every configured EMA pair.

    Output:
        dictionary containing crossover information for
        every EMA pair
    """

    results = {}

    for fast_period, slow_period in EMA_PAIRS:

        fast_ema = indicator_state["ema"].get(
            fast_period,
            np.nan,
        )

        slow_ema = indicator_state["ema"].get(
            slow_period,
            np.nan,
        )

        crossover_price = calculate_ema_crossover_price(
            fast_ema=fast_ema,
            slow_ema=slow_ema,
            fast_period=fast_period,
            slow_period=slow_period,
        )

        direction = get_ema_crossover_direction(
            fast_ema,
            slow_ema,
        )

        pair_name = f"{fast_period}_{slow_period}"

        results[pair_name] = {
            "fast_period": fast_period,
            "slow_period": slow_period,
            "fast_ema": fast_ema,
            "slow_ema": slow_ema,
            "direction": direction,
            "crossover_price": crossover_price,
        }

    return results


# ============================================================
# GET SPECIFIC EMA CROSSOVER
# ============================================================

def get_ema_crossover_strategy(
    indicator_state,
    fast_period,
    slow_period,
):
    """
    Input:
        indicator_state: current indicator state
        fast_period: fast EMA period
        slow_period: slow EMA period

    Description:
        Calculates the EMA crossover price for one specific
        EMA pair.

    Output:
        dictionary containing the strategy result
    """

    fast_ema = indicator_state["ema"].get(
        fast_period,
        np.nan,
    )

    slow_ema = indicator_state["ema"].get(
        slow_period,
        np.nan,
    )

    crossover_price = calculate_ema_crossover_price(
        fast_ema=fast_ema,
        slow_ema=slow_ema,
        fast_period=fast_period,
        slow_period=slow_period,
    )

    direction = get_ema_crossover_direction(
        fast_ema,
        slow_ema,
    )

    return {
        "fast_period": fast_period,
        "slow_period": slow_period,
        "fast_ema": fast_ema,
        "slow_ema": slow_ema,
        "direction": direction,
        "crossover_price": crossover_price,
    }


# ============================================================
# STRATEGY DISPATCHER
# ============================================================

def calculate_strategy(
    strategy_name,
    indicator_state,
):
    """
    Input:
        strategy_name: name of the strategy
        indicator_state: current indicator state

    Description:
        Runs the requested strategy.

    Output:
        strategy result
    """

    if strategy_name == "ema_crossover":

        return calculate_ema_crossover_strategy(
            indicator_state
        )

    raise ValueError(
        f"Unknown strategy: {strategy_name}"
    )