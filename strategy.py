"""
strategy.py - Reusable Strategy Library

Converts indicator information into strategy-specific trade parameters and 
determines entry validity for both live trading and historical simulation.
"""

from __future__ import annotations
import math
from typing import Dict, Tuple, Optional


# ========= Start: 4.1 EMA Crossover Detection =============
def detect_crossover(
    previous_fast_ema: float,
    previous_slow_ema: float,
    current_fast_ema: float,
    current_slow_ema: float
) -> bool:
    """
    Determines whether the EMA relationship represents a long entry crossover.
    Historical simulation uses actual bar values. Long entries only.
    """
    if any(math.isnan(x) for x in (previous_fast_ema, previous_slow_ema, current_fast_ema, current_slow_ema)):
        return False

    return (previous_fast_ema <= previous_slow_ema) and (current_fast_ema > current_slow_ema)
# ====== End: 4.1 EMA Crossover Detection =======


# ========= Start: 4.2 Crossover Price Calculation =============
def calculate_crossover_price(
    fast_period: int,
    slow_period: int,
    previous_fast_ema: float,
    previous_slow_ema: float
) -> float:
    """
    Calculates the current price required for the fast EMA to cross above the slow EMA.
    Uses previous EMA state to derive the live crossover price threshold.
    Formula: P = ((1 - alpha_slow) * EMA_slow_prev - (1 - alpha_fast) * EMA_fast_prev) / (alpha_fast - alpha_slow)
    """
    if fast_period <= 0 or slow_period <= 0 or fast_period == slow_period:
        return float(previous_slow_ema)

    alpha_fast = 2.0 / (fast_period + 1.0)
    alpha_slow = 2.0 / (slow_period + 1.0)

    denominator = alpha_fast - alpha_slow
    if abs(denominator) < 1e-12:
        return float(previous_slow_ema)

    numerator = (1.0 - alpha_slow) * previous_slow_ema - (1.0 - alpha_fast) * previous_fast_ema

    return float(numerator / denominator)
# ====== End: 4.2 Crossover Price Calculation =======


# ========= Start: 4.3 Entry Range Validation =============
def is_entry_valid(
    current_price: float,
    crossover_price: float,
    green_avg: float,
    red_avg: float,
    range_multiplier: int = 15
) -> bool:
    """
    Determines whether the calculated crossover entry price is within the allowed
    volatility envelope relative to current price.
    Rule: current_price - (15 * red_avg) <= crossover_price <= current_price + (15 * green_avg)
    """
    if any(math.isnan(x) for x in (current_price, crossover_price, green_avg, red_avg)):
        return False

    lower_bound = current_price - (range_multiplier * max(0.0, red_avg))
    upper_bound = current_price + (range_multiplier * max(0.0, green_avg))

    return lower_bound <= crossover_price <= upper_bound
# ====== End: 4.3 Entry Range Validation =======


# ========= Start: 4.4 Stop Loss / Take Profit Calculation =============
def calculate_sl_tp(
    entry_price: float,
    red_avg: float,
    sl_multiplier: float,
    risk_reward: float
) -> Tuple[float, float]:
    """
    Converts red-candle average, SL multiplier, and RR into absolute SL and TP levels.
    SL distance = red_avg * sl_multiplier
    TP distance = SL distance * risk_reward
    Returns (stop_loss, take_profit).
    """
    sl_distance = max(0.0, red_avg) * max(0.0, sl_multiplier)
    tp_distance = sl_distance * max(0.0, risk_reward)

    stop_loss = max(0.01, entry_price - sl_distance)
    take_profit = entry_price + tp_distance

    return float(stop_loss), float(take_profit)
# ====== End: 4.4 Stop Loss / Take Profit Calculation =======


# ========= Start: 4.5 Trade Levels =============
class TradeLevels:
    """
    Data container holding strategy-generated price targets for a trade setup.
    Contains no broker, execution, or capital parameters.
    """
    def __init__(self, entry_price: float, stop_loss: float, take_profit: float):
        self.entry_price = float(entry_price)
        self.stop_loss = float(stop_loss)
        self.take_profit = float(take_profit)

    def to_dict(self) -> Dict[str, float]:
        return {
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit
        }

    def __repr__(self) -> str:
        return f"TradeLevels(entry_price={self.entry_price:.2f}, stop_loss={self.stop_loss:.2f}, take_profit={self.take_profit:.2f})"
# ====== End: 4.5 Trade Levels =======


# ========= Start: 4.6 Strategy Interface =============
def calculate_trade_levels(
    entry_price: float,
    red_avg: float,
    sl_multiplier: float,
    risk_reward: float
) -> TradeLevels:
    """
    Generates a complete TradeLevels object using the strategy calculation rules.
    """
    stop_loss, take_profit = calculate_sl_tp(
        entry_price=entry_price,
        red_avg=red_avg,
        sl_multiplier=sl_multiplier,
        risk_reward=risk_reward
    )
    return TradeLevels(
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit
    )


def evaluate_live_entry(
    fast_period: int,
    slow_period: int,
    previous_fast_ema: float,
    previous_slow_ema: float,
    current_price: float,
    green_avg: float,
    red_avg: float,
    sl_multiplier: float,
    risk_reward: float,
    range_multiplier: int = 15
) -> Tuple[bool, float, Optional[TradeLevels]]:
    """
    Unified public interface function for live trading order evaluation.
    Calculates predicted crossover price, verifies entry range validity, 
    and outputs (is_valid, crossover_price, TradeLevels).
    """
    crossover_price = calculate_crossover_price(
        fast_period=fast_period,
        slow_period=slow_period,
        previous_fast_ema=previous_fast_ema,
        previous_slow_ema=previous_slow_ema
    )

    valid = is_entry_valid(
        current_price=current_price,
        crossover_price=crossover_price,
        green_avg=green_avg,
        red_avg=red_avg,
        range_multiplier=range_multiplier
    )

    if not valid:
        return False, crossover_price, None

    levels = calculate_trade_levels(
        entry_price=crossover_price,
        red_avg=red_avg,
        sl_multiplier=sl_multiplier,
        risk_reward=risk_reward
    )

    return True, crossover_price, levels
# ====== End: 4.6 Strategy Interface =======