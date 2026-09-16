"""
simulation.py
=============
Type: Strategy Simulation Engine
Purpose: Historical backtesting and simulation loop for trading strategy methods.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional, Tuple, Union
from dataclasses import dataclass

# Internal dependencies defined across Level-0/1 specifications
import config
from methods import Method, get_method_id
import indicators
import strategy


# ==============================================================================
# ========= Start: 6.4.1 Simulation Data Structures ===========================
# ==============================================================================

@dataclass
class SimulatedTrade:
    """
    Standardized internal structure representing a completed trade during historical backtesting.
    """
    method_id: str
    symbol: str
    timeframe: str
    entry_timestamp: str
    exit_timestamp: str
    entry_price: float
    exit_price: float


@dataclass
class ActivePosition:
    """
    Tracks an in-flight simulated position across historical candle iterations.
    """
    method_id: str
    entry_timestamp: str
    entry_price: float
    stop_loss: float
    take_profit: float

# ==============================================================================
# ========= End: 6.4.1 Simulation Data Structures =============================
# ==============================================================================


# ==============================================================================
# ========= Start: 6.4.2 Historical Bar Iteration & State Setup ===============
# ==============================================================================

def _prepare_historical_bars(bars_data: Union[pd.DataFrame, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """
    Converts DataFrame or bar wrapper rows to standard dictionary format for deterministic chronological iteration.
    """
    if isinstance(bars_data, pd.DataFrame):
        df = bars_data.copy()
        if "timestamp" in df.columns:
            df = df.sort_values("timestamp")
        records = df.to_dict("records")
    elif isinstance(bars_data, list):
        records = bars_data
    elif hasattr(bars_data, "to_dict"):
        records = bars_data.to_dict("records")
    elif hasattr(bars_data, "df") and isinstance(bars_data.df, pd.DataFrame):
        df = bars_data.df.copy()
        if "timestamp" in df.columns:
            df = df.sort_values("timestamp")
        records = df.to_dict("records")
    else:
        records = []

    # Standardize timestamp field to string for consistent comparison
    for r in records:
        if "timestamp" in r and r["timestamp"] is not None:
            r["timestamp"] = str(r["timestamp"])

    return records


def _initialize_bar_indicators(bars: List[Dict[str, Any]], fast_period: int, slow_period: int) -> List[Any]:
    """
    Pre-computes historical indicator values across the bar series for fast crossover checking.
    """
    df = pd.DataFrame(bars)
    if df.empty:
        return []

    # Calculate indicators over full series
    df = indicators.calculate_indicators(df)
    
    # Extract calculated indicator states per bar
    indicator_states = []
    for _, row in df.iterrows():
        state_dict = {
            "ema": {
                fast_period: row.get(f"ema_{fast_period}", row.get("ema_fast", 0.0)),
                slow_period: row.get(f"ema_{slow_period}", row.get("ema_slow", 0.0))
            },
            "red_avg": row.get("red_avg", row.get("atr", row.get("close", 0.0) * 0.01))
        }
        indicator_states.append(state_dict)

    return indicator_states

# ==============================================================================
# ========= End: 6.4.2 Historical Bar Iteration & State Setup =================
# ==============================================================================


# ==============================================================================
# ========= Start: 6.4.3 Trade Resolution (SL/TP Engine) ======================
# ==============================================================================

def _check_bar_sl_tp(
    position: ActivePosition,
    bar: Dict[str, Any]
) -> Optional[Tuple[float, str]]:
    """
    Evaluates whether a high/low on the current historical bar hits the stop loss or take profit.
    """
    bar_low = float(bar["low"])
    bar_high = float(bar["high"])
    bar_time = str(bar["timestamp"])
    
    hit_sl = bar_low <= position.stop_loss
    hit_tp = bar_high >= position.take_profit
    
    if hit_sl and hit_tp:
        # Same-candle ambiguity -> conservative fallback to SL
        return (position.stop_loss, bar_time)
    elif hit_sl:
        return (position.stop_loss, bar_time)
    elif hit_tp:
        return (position.take_profit, bar_time)
        
    return None

# ==============================================================================
# ========= End: 6.4.3 Trade Resolution (SL/TP Engine) ========================
# ==============================================================================


# ==============================================================================
# ========= Start: 6.4.4 Single-Method Simulation Loop ========================
# ==============================================================================

def simulate_method_on_series(
    method: Method,
    bars: List[Dict[str, Any]],
    cutoff_exit_timestamp: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Executes historical strategy simulation for one method over a timeframe's bar series.
    """
    method_id = get_method_id(method)
    min_periods = getattr(config, "EMA_PERIODS", [9, 21, 50, 200])
    max_lookback = max(min_periods) if min_periods else 50

    if len(bars) < max_lookback:
        return []

    completed_trades: List[Dict[str, Any]] = []
    active_pos: Optional[ActivePosition] = None
    
    # Extract EMA parameters safely
    if hasattr(method, "ema_pair") and method.ema_pair:
        fast_period, slow_period = method.ema_pair
    else:
        fast_period = getattr(method, "ema_fast", 9)
        slow_period = getattr(method, "ema_slow", 21)

    sl_mult = getattr(method, "sl_multiplier", 1.5)
    rr = getattr(method, "risk_reward", 2.0)

    # Pre-build indicator state history for chronological evaluation
    indicator_states = _initialize_bar_indicators(bars, fast_period, slow_period)
    if not indicator_states:
        return []

    for idx in range(1, len(bars)):
        current_bar = bars[idx]
        current_time = str(current_bar["timestamp"])
        
        # 1. Evaluate open active trade
        if active_pos is not None:
            resolution = _check_bar_sl_tp(active_pos, current_bar)
            if resolution is not None:
                exit_price, exit_time = resolution
                
                # Check cutoff filter to avoid duplicating historical trades
                if cutoff_exit_timestamp is None or exit_time > str(cutoff_exit_timestamp):
                    completed_trades.append({
                        "method_id": method_id,
                        "symbol": method.symbol,
                        "timeframe": method.timeframe,
                        "entry_timestamp": active_pos.entry_timestamp,
                        "exit_timestamp": exit_time,
                        "entry_price": active_pos.entry_price,
                        "exit_price": exit_price
                    })
                active_pos = None

        # 2. Check crossover entry if no trade is open
        if active_pos is None:
            prev_state = indicator_states[idx - 1]
            curr_state = indicator_states[idx]
            
            prev_fast = prev_state["ema"].get(fast_period, 0.0)
            prev_slow = prev_state["ema"].get(slow_period, 0.0)
            curr_fast = curr_state["ema"].get(fast_period, 0.0)
            curr_slow = curr_state["ema"].get(slow_period, 0.0)
            
            is_crossover = strategy.detect_crossover(
                previous_fast_ema=prev_fast,
                previous_slow_ema=prev_slow,
                current_fast_ema=curr_fast,
                current_slow_ema=curr_slow
            )
            
            if is_crossover:
                entry_price = float(current_bar["close"])
                red_avg = curr_state.get("red_avg", entry_price * 0.01)
                
                # Calculate SL / TP using strategy module
                levels = strategy.calculate_trade_levels(
                    entry_price=entry_price,
                    red_avg=red_avg,
                    sl_multiplier=sl_mult,
                    risk_reward=rr
                )
                
                # Extract stop loss and take profit safely from dataclass or dict
                sl_val = getattr(levels, "stop_loss", levels.get("stop_loss", entry_price * 0.98) if isinstance(levels, dict) else entry_price * 0.98)
                tp_val = getattr(levels, "take_profit", levels.get("take_profit", entry_price * 1.04) if isinstance(levels, dict) else entry_price * 1.04)

                active_pos = ActivePosition(
                    method_id=method_id,
                    entry_timestamp=current_time,
                    entry_price=entry_price,
                    stop_loss=sl_val,
                    take_profit=tp_val
                )

    # 3. Close open positions at final bar boundary
    if active_pos is not None:
        final_bar = bars[-1]
        final_time = str(final_bar["timestamp"])
        final_close = float(final_bar["close"])
        
        if cutoff_exit_timestamp is None or final_time > str(cutoff_exit_timestamp):
            completed_trades.append({
                "method_id": method_id,
                "symbol": method.symbol,
                "timeframe": method.timeframe,
                "entry_timestamp": active_pos.entry_timestamp,
                "exit_timestamp": final_time,
                "entry_price": active_pos.entry_price,
                "exit_price": final_close
            })

    return completed_trades

# ==============================================================================
# ========= End: 6.4.4 Single-Method Simulation Loop ==========================
# ==============================================================================


# ==============================================================================
# ========= Start: 6.4.5 Simulator Orchestration / Main Interface ============
# ==============================================================================

def run_simulation(
    market_data: Any,
    methods: List[Method],
    cutoffs: Optional[Dict[str, Optional[str]]] = None,
    start_time: Optional[Any] = None
) -> List[Dict[str, Any]]:
    """
    Public entry point for simulation.py. Iterates through all methods for a given stock,
    processes historical candles, and returns new completed trades.
    """
    if cutoffs is None:
        cutoffs = {}
        
    all_completed_trades: List[Dict[str, Any]] = []
    
    # Pre-parse bar arrays per timeframe from MarketData dict or DataManager instance
    parsed_bars: Dict[str, List[Dict[str, Any]]] = {}

    if hasattr(market_data, "datasets"):
        # Handling DataManager object
        for tf, dataset in market_data.datasets.items():
            parsed_bars[tf] = _prepare_historical_bars(dataset)
    elif isinstance(market_data, dict):
        for tf, data in market_data.items():
            parsed_bars[tf] = _prepare_historical_bars(data)
            
    # Simulate each method independently
    for method in methods:
        tf = method.timeframe
        if tf not in parsed_bars or not parsed_bars[tf]:
            continue
            
        bars = parsed_bars[tf]
        method_id = get_method_id(method)
        cutoff = cutoffs.get(method_id, None) if isinstance(cutoffs, dict) else None
        
        method_trades = simulate_method_on_series(
            method=method,
            bars=bars,
            cutoff_exit_timestamp=cutoff
        )
        
        all_completed_trades.extend(method_trades)
        
    return all_completed_trades


def run_historical_simulation(
    market_data: Any,
    methods: List[Method],
    start_time: Optional[Any] = None,
    cutoffs: Optional[Dict[str, Optional[str]]] = None
) -> List[Dict[str, Any]]:
    """
    Alias entry point matching standard orchestration imports in morning.py.
    """
    return run_simulation(
        market_data=market_data,
        methods=methods,
        cutoffs=cutoffs,
        start_time=start_time
    )

# ==============================================================================
# ========= End: 6.4.5 Simulator Orchestration / Main Interface ==============
# ==============================================================================