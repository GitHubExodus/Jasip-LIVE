"""
indicators.py - Reusable Indicator Library

Maintains and updates technical indicators (EMA, ROC, Green/Red Candle Averages)
for stock timeframes cleanly and incrementally without rescanning historical data.
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any


# ==============================================================================
# ========== Start: Part 3.4 Rolling-Window State =============================
# ==============================================================================

class RollingWindow:
    """
    Generic O(1) fixed-size rolling window queue.
    Maintains a running sum and bounded queue for incremental updates.
    Formula: Sum_new = Sum_old - x_old + x_new
    """
    def __init__(self, size: int):
        if size <= 0:
            raise ValueError("Window size must be greater than zero.")
        self.size: int = size
        self.queue: List[float] = []
        self.running_sum: float = 0.0

    def add(self, value: float) -> float:
        """
        Appends a new value to the rolling window and ejects the oldest if at capacity.
        Returns the updated average across the window.
        """
        self.queue.append(value)
        self.running_sum += value
        
        if len(self.queue) > self.size:
            oldest = self.queue.pop(0)
            self.running_sum -= oldest
            
        return self.get_average()

    def replace_latest(self, value: float) -> float:
        """
        Replaces the current forming/unclosed value in the queue without advancing window time.
        Used for intra-bar 1-minute live tick updates.
        """
        if not self.queue:
            return self.add(value)
        
        old_val = self.queue[-1]
        self.running_sum = self.running_sum - old_val + value
        self.queue[-1] = value
        return self.get_average()

    def get_average(self) -> float:
        """Returns the current simple average of elements inside the queue."""
        if not self.queue:
            return 0.0
        return self.running_sum / len(self.queue)

    def get_oldest(self) -> float:
        """Returns the oldest value in the window (used for explicit ROC tracking)."""
        if not self.queue:
            return 0.0
        return self.queue[0]

    def is_full(self) -> bool:
        """Checks whether the rolling window has reached its max capacity."""
        return len(self.queue) == self.size

    def snapshot(self) -> Dict[str, Any]:
        """Serializes current internal state for persistence or rollback."""
        return {
            "size": self.size,
            "queue": list(self.queue),
            "running_sum": self.running_sum
        }

    @classmethod
    def restore(cls, data: Dict[str, Any]) -> "RollingWindow":
        """Reconstructs a RollingWindow instance from stored state data."""
        win = cls(size=data["size"])
        win.queue = list(data["queue"])
        win.running_sum = float(data["running_sum"])
        return win

# ==============================================================================
# ========== End: Part 3.4 Rolling-Window State ===============================
# ==============================================================================


# ==============================================================================
# ========== Start: Part 3.1 EMA Calculation ===================================
# ==============================================================================

class EMACalculator:
    """
    Provides full historical and single-step incremental EMA calculations.
    Multiplier (alpha) = 2 / (period + 1)
    Incremental formula: EMA_new = alpha * price_new + (1 - alpha) * EMA_previous
    """
    @staticmethod
    def calculate_alpha(period: int) -> float:
        return 2.0 / (period + 1.0)

    @classmethod
    def calculate_series(cls, prices: List[float], period: int) -> List[float]:
        """
        Calculates historical EMA series over a full list of close prices.
        Initializes first EMA value as SMA of first 'period' elements.
        """
        if len(prices) < period:
            return []
        
        ema_series: List[float] = [0.0] * len(prices)
        # Initial SMA
        initial_sma = sum(prices[:period]) / float(period)
        ema_series[period - 1] = initial_sma
        
        alpha = cls.calculate_alpha(period)
        for i in range(period, len(prices)):
            ema_series[i] = (prices[i] * alpha) + (ema_series[i - 1] * (1.0 - alpha))
            
        return ema_series

    @classmethod
    def update_single(cls, current_price: float, prev_ema: float, period: int) -> float:
        """
        Performs O(1) single-step incremental EMA calculation.
        """
        alpha = cls.calculate_alpha(period)
        return (current_price * alpha) + (prev_ema * (1.0 - alpha))

# ==============================================================================
# ========== End: Part 3.1 EMA Calculation =====================================
# ==============================================================================


# ==============================================================================
# ========== Start: Part 3.2 ROC Calculation ===================================
# ==============================================================================

class ROCCalculator:
    """
    Calculates Rate of Change over N periods:
    ROC = ((Current Price - Price N Bars Ago) / Price N Bars Ago) * 100
    Maintains a price history queue to perform updates in O(1) time complexity.
    """
    def __init__(self, period: int = 30):
        self.period: int = period
        self.price_window: RollingWindow = RollingWindow(size=period + 1)

    def initialize(self, prices: List[float]) -> float:
        """Populates the buffer with historical prices and returns latest ROC."""
        for p in prices:
            self.price_window.add(p)
        return self.get_roc(prices[-1] if prices else 0.0)

    def update(self, current_price: float, is_new_bar: bool = True) -> float:
        """Updates rolling price window and returns computed ROC."""
        if is_new_bar:
            self.price_window.add(current_price)
        else:
            self.price_window.replace_latest(current_price)
        return self.get_roc(current_price)

    def get_roc(self, current_price: float) -> float:
        """Computes current ROC against the oldest price in buffer."""
        if not self.price_window.is_full():
            return 0.0
        
        past_price = self.price_window.get_oldest()
        if past_price == 0.0 or math.isnan(past_price):
            return 0.0
            
        return ((current_price - past_price) / past_price) * 100.0

# ==============================================================================
# ========== End: Part 3.2 ROC Calculation =====================================
# ==============================================================================


# ==============================================================================
# ========== Start: Part 3.3 Candle Average Calculation =======================
# ==============================================================================

class CandleAverageCalculator:
    """
    Maintains rolling windows for green and red candle magnitudes over N candles (default 200).
    Green candle magnitude: ((close - open) / open) * 100
    Red candle magnitude  : ((open - close) / open) * 100 (always positive magnitude)
    """
    def __init__(self, window_size: int = 200):
        self.window_size: int = window_size
        self.green_window: RollingWindow = RollingWindow(size=window_size)
        self.red_window: RollingWindow = RollingWindow(size=window_size)

    @staticmethod
    def compute_candle_magnitudes(open_price: float, close_price: float) -> Tuple[float, float]:
        """Returns (green_magnitude, red_magnitude) for a bar. Non-applicable side gets 0.0."""
        if open_price <= 0.0 or math.isnan(open_price) or math.isnan(close_price):
            return 0.0, 0.0
            
        if close_price >= open_price:
            green_mag = ((close_price - open_price) / open_price) * 100.0
            return green_mag, 0.0
        else:
            red_mag = ((open_price - close_price) / open_price) * 100.0
            return 0.0, red_mag

    def initialize(self, bars: List[Dict[str, float]]) -> Tuple[float, float]:
        """Populates rolling windows with historical candle data."""
        for bar in bars:
            g_mag, r_mag = self.compute_candle_magnitudes(bar["open"], bar["close"])
            self.green_window.add(g_mag)
            self.red_window.add(r_mag)
            
        return self.green_window.get_average(), self.red_window.get_average()

    def update(self, open_price: float, close_price: float, is_new_bar: bool = True) -> Tuple[float, float]:
        """Performs incremental green/red rolling average update."""
        g_mag, r_mag = self.compute_candle_magnitudes(open_price, close_price)
        
        if is_new_bar:
            green_avg = self.green_window.add(g_mag)
            red_avg = self.red_window.add(r_mag)
        else:
            green_avg = self.green_window.replace_latest(g_mag)
            red_avg = self.red_window.replace_latest(r_mag)
            
        return green_avg, red_avg

# ==============================================================================
# ========== End: Part 3.3 Candle Average Calculation =========================
# ==============================================================================


# ==============================================================================
# ========== Start: Part 3.5 Indicator State ===================================
# ==============================================================================

@dataclass
class IndicatorState:
    """
    Unified container holding the complete current state and persistent tracking queues
    for an individual stock and timeframe.
    """
    symbol: str
    timeframe: str
    ema: Dict[int, float] = field(default_factory=dict)
    roc: float = 0.0
    green_avg: float = 0.0
    red_avg: float = 0.0
    
    # Internal state tracking objects (prevents historical rescan)
    _roc_calculator: Optional[ROCCalculator] = field(default=None, repr=False)
    _candle_calculator: Optional[CandleAverageCalculator] = field(default=None, repr=False)
    _last_bar_timestamp: Optional[Any] = field(default=None, repr=False)
    _closed_ema: Dict[int, float] = field(default_factory=dict, repr=False)

    def copy_values(self) -> Dict[str, Any]:
        """Export clean snapshot dictionary for execution/strategy consumption."""
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "ema": dict(self.ema),
            "roc": self.roc,
            "green_avg": self.green_avg,
            "red_avg": self.red_avg
        }

# ==============================================================================
# ========== End: Part 3.5 Indicator State =====================================
# ==============================================================================


# ==============================================================================
# ========== Start: Part 3.6 Indicator Interface ==============================
# ==============================================================================

def initialize_indicators(
    symbol: str,
    timeframe: str,
    bars: List[Dict[str, Any]],
    ema_periods: Tuple[int, ...] = (3, 5, 9, 14, 21, 30, 50, 100, 200),
    roc_period: int = 30,
    candle_window: int = 200
) -> IndicatorState:
    """
    Public API Operation 1: Complete Initial Calculation from Historical Data.
    Performs full initial calculations over historical bars and returns an initialized IndicatorState.
    """
    if not bars:
        raise ValueError(f"Cannot initialize indicators for {symbol} ({timeframe}): bars list is empty.")

    closes = [float(b["close"]) for b in bars]
    
    # 1. EMAs Initial Calculation
    ema_state: Dict[int, float] = {}
    for period in ema_periods:
        series = EMACalculator.calculate_series(closes, period)
        ema_state[period] = series[-1] if series else closes[-1]

    # 2. ROC Initial Calculation
    roc_calc = ROCCalculator(period=roc_period)
    initial_roc = roc_calc.initialize(closes)

    # 3. Green/Red Candle Average Initial Calculation
    candle_calc = CandleAverageCalculator(window_size=candle_window)
    initial_green_avg, initial_red_avg = candle_calc.initialize(bars)

    # Construct unified state model
    state = IndicatorState(
        symbol=symbol,
        timeframe=timeframe,
        ema=dict(ema_state),
        roc=initial_roc,
        green_avg=initial_green_avg,
        red_avg=initial_red_avg,
        _roc_calculator=roc_calc,
        _candle_calculator=candle_calc,
        _last_bar_timestamp=bars[-1].get("timestamp"),
        _closed_ema=dict(ema_state)
    )

    return state


def update_indicators(
    previous_state: IndicatorState,
    current_bar: Dict[str, Any],
    ema_periods: Tuple[int, ...] = (3, 5, 9, 14, 21, 30, 50, 100, 200)
) -> IndicatorState:
    """
    Public API Operation 2: Incremental Real-time Update.
    Updates an existing IndicatorState in O(1) time using incoming live tick/bar data.
    Automatically handles bar replacement vs appending based on candle timestamps.
    """
    bar_timestamp = current_bar.get("timestamp")
    is_new_bar = (bar_timestamp != previous_state._last_bar_timestamp)

    current_close = float(current_bar["close"])
    current_open = float(current_bar["open"])

    # Ensure calculator sub-objects are present
    if previous_state._roc_calculator is None:
        previous_state._roc_calculator = ROCCalculator()
    if previous_state._candle_calculator is None:
        previous_state._candle_calculator = CandleAverageCalculator()

    # Store baseline EMA of closed bar if initializing baseline
    if not previous_state._closed_ema:
        previous_state._closed_ema = dict(previous_state.ema)

    # If transitioning to a new bar, update the closed EMA baseline to previous candle's final value
    if is_new_bar:
        previous_state._closed_ema = dict(previous_state.ema)

    # 1. Incremental EMA update
    updated_ema: Dict[int, float] = {}
    for period in ema_periods:
        # Evaluate against previous closed candle baseline to prevent intraday tick drift
        anchor_ema = previous_state._closed_ema.get(period, current_close)
        updated_ema[period] = EMACalculator.update_single(current_close, anchor_ema, period)

    # 2. Incremental ROC update
    updated_roc = previous_state._roc_calculator.update(current_close, is_new_bar=is_new_bar)

    # 3. Incremental Green/Red Candle Average update
    updated_green, updated_red = previous_state._candle_calculator.update(
        open_price=current_open,
        close_price=current_close,
        is_new_bar=is_new_bar
    )

    # Update state values inline
    previous_state.ema = updated_ema
    previous_state.roc = updated_roc
    previous_state.green_avg = updated_green
    previous_state.red_avg = updated_red
    
    if is_new_bar:
        previous_state._last_bar_timestamp = bar_timestamp

    return previous_state

# ==============================================================================
# ========== End: Part 3.6 Indicator Interface ================================
# ==============================================================================