import numpy as np

from old.config import (
    EMA_PAIRS,
)


# ============================================================
# STRATEGY INFORMATION
# ============================================================

def get_ema_pair(
    strategy,
):
    """
    strategy_1 -> EMA 3 / EMA 5
    strategy_2 -> EMA 5 / EMA 9
    ...
    """

    index = (
        int(strategy) - 1
    )

    if index < 0 or index >= len(
        EMA_PAIRS
    ):

        raise ValueError(
            f"Unsupported strategy: {strategy}"
        )

    return EMA_PAIRS[index]


# ============================================================
# CURRENT SIGNAL
# ============================================================

def bullish_entry_now(
    previous_fast_ema,
    previous_slow_ema,
    current_price,
    fast_period,
    slow_period,
):
    """
    Determine whether the current price produces
    a bullish EMA crossover.

    Previous candle must not already be bullish.

    Current EMA values are calculated from the
    current price.
    """

    if not np.isfinite(
        previous_fast_ema
    ):

        return False

    if not np.isfinite(
        previous_slow_ema
    ):

        return False

    if not np.isfinite(
        current_price
    ):

        return False

    if (
        previous_fast_ema
        >
        previous_slow_ema
    ):

        return False

    alpha_fast = (
        2.0
        /
        (fast_period + 1.0)
    )

    alpha_slow = (
        2.0
        /
        (slow_period + 1.0)
    )

    current_fast = (
        alpha_fast
        * current_price
        +
        (1.0 - alpha_fast)
        * previous_fast_ema
    )

    current_slow = (
        alpha_slow
        * current_price
        +
        (1.0 - alpha_slow)
        * previous_slow_ema
    )

    return (
        current_fast
        >
        current_slow
    )


# ============================================================
# ENTRY THRESHOLD
# ============================================================

def calculate_entry_threshold(
    previous_fast_ema,
    previous_slow_ema,
    fast_period,
    slow_period,
):
    """
    Solve:

        current_fast_ema > current_slow_ema

    for current price.

    Returns the minimum price required
    to produce the crossover.

    This threshold belongs to the current
    forming candle and stays fixed until
    the next candle begins.
    """

    if not np.isfinite(
        previous_fast_ema
    ):

        return np.nan

    if not np.isfinite(
        previous_slow_ema
    ):

        return np.nan

    alpha_fast = (
        2.0
        /
        (fast_period + 1.0)
    )

    alpha_slow = (
        2.0
        /
        (slow_period + 1.0)
    )

    numerator = (
        (
            1.0
            - alpha_slow
        )
        * previous_slow_ema
        -
        (
            1.0
            - alpha_fast
        )
        * previous_fast_ema
    )

    denominator = (
        alpha_fast
        -
        alpha_slow
    )

    if denominator <= 0.0:

        return np.nan

    threshold = (
        numerator
        /
        denominator
    )

    return float(
        threshold
    )


# ============================================================
# BUILD STRATEGY STATE
# ============================================================

def build_strategy_state(
    strategy,
    previous_fast_ema,
    previous_slow_ema,
    current_price,
):
    fast_period, slow_period = (
        get_ema_pair(
            strategy
        )
    )

    threshold = (
        calculate_entry_threshold(
            previous_fast_ema,
            previous_slow_ema,
            fast_period,
            slow_period,
        )
    )

    entry = False

    if np.isfinite(
        threshold
    ):

        entry = (
            current_price
            >=
            threshold
        )

    return {
        "strategy": strategy,

        "fast_period": fast_period,

        "slow_period": slow_period,

        "target_price": threshold,

        "entry": entry,
    }


# ============================================================
# STRATEGY NAME
# ============================================================

def strategy_name(
    strategy,
):
    return (
        f"strategy_{int(strategy)}"
    )