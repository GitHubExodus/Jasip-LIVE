# strategies.py

import pandas as pd

from old3.config import EMA_PAIRS


def ema_cross(data, fast, slow):
    """
    Detect an actual bullish EMA crossover.

    Previous bar:
        fast <= slow

    Current bar:
        fast > slow

    Returns:
        True  -> actual BUY crossover
        False -> no crossover
    """

    if len(data) < 2:
        return False

    fast_column = f"ema_{fast}"
    slow_column = f"ema_{slow}"

    previous_fast = data[fast_column].iloc[-2]
    previous_slow = data[slow_column].iloc[-2]

    current_fast = data[fast_column].iloc[-1]
    current_slow = data[slow_column].iloc[-1]

    return (
        previous_fast <= previous_slow
        and
        current_fast > current_slow
    )


def get_signals(data):
    """
    Check every configured EMA pair.

    Returns only actual bullish crossover events.
    """

    signals = []

    for fast, slow in EMA_PAIRS:
        if ema_cross(data, fast, slow):
            signals.append({
                "strategy": "ema_cross",
                "fast": fast,
                "slow": slow,
            })

    return signals