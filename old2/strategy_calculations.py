# strategy_calculations.py

import numpy as np


# ============================================================
# EMA CROSSOVER PRICE
# ============================================================

def calculate_ema_crossover_price(
    fast_ema,
    slow_ema,
    fast_period,
    slow_period,
):
    """
    Input:
        fast_ema: previous fast EMA value
        slow_ema: previous slow EMA value
        fast_period: fast EMA period
        slow_period: slow EMA period

    Description:
        Calculates the price required for the fast EMA to equal
        the slow EMA on the next calculation bar.

        This is the crossover price for a bullish EMA crossover.

        Formula:

        P = (
            (1 - alpha_slow) * EMA_slow
            - (1 - alpha_fast) * EMA_fast
        ) / (
            alpha_fast - alpha_slow
        )

        where:

        alpha = 2 / (period + 1)

    Output:
        float
    """

    if (
        np.isnan(fast_ema)
        or np.isnan(slow_ema)
    ):
        return np.nan

    if fast_period >= slow_period:
        raise ValueError(
            "fast_period must be smaller than slow_period"
        )

    alpha_fast = 2.0 / (
        fast_period + 1.0
    )

    alpha_slow = 2.0 / (
        slow_period + 1.0
    )

    denominator = (
        alpha_fast - alpha_slow
    )

    if denominator == 0.0:
        return np.nan

    crossover_price = (
        (
            (1.0 - alpha_slow) * slow_ema
            -
            (1.0 - alpha_fast) * fast_ema
        )
        / denominator
    )

    return crossover_price


# ============================================================
# EMA CROSSOVER DIRECTION
# ============================================================

def get_ema_crossover_direction(
    fast_ema,
    slow_ema,
):
    """
    Input:
        fast_ema: current fast EMA
        slow_ema: current slow EMA

    Description:
        Determines the current relationship between the
        fast and slow EMA.

    Output:
        "above", "below", or None
    """

    if (
        np.isnan(fast_ema)
        or np.isnan(slow_ema)
    ):
        return None

    if fast_ema > slow_ema:
        return "above"

    if fast_ema < slow_ema:
        return "below"

    return None