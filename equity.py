"""
equity.py
=========
Type: Core Module
Purpose: Manages equity curve updates, method performance tracking, and 
         rate-of-change (ROC) calculations per stock and method.
"""

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

# Internal Architecture Imports
import config
from methods import Method, get_method_id
import simulation


# ==============================================================================
# ========= Start: 6.1 Equity Data Model =======================================
# ==============================================================================

@dataclass
class EquityRecord:
    """
    Standardized data container representing the equity state resulting from a completed trade.
    """
    method_id: str
    symbol: str
    timeframe: str
    strategy: str
    sl_multiplier: float
    risk_reward: float
    entry_timestamp: str
    exit_timestamp: str
    entry_price: float
    exit_price: float
    trade_return: float  # Percentage return, e.g., 0.20 for +20%
    equity: float        # Accumulated method equity level
    roc: float          # Method equity-curve ROC 30


class EquityData:
    """
    State container for all method equity records associated with a specific stock.
    Maintains chronological ordering by exit timestamp.
    """
    def __init__(self, symbol: str, records: Optional[List[EquityRecord]] = None):
        self.symbol = symbol
        self.records: List[EquityRecord] = records if records is not None else []

    def to_dataframe(self) -> pd.DataFrame:
        """Converts the internal equity records into a Parquet-ready DataFrame."""
        if not self.records:
            return pd.DataFrame(columns=[
                "method_id", "symbol", "timeframe", "strategy", "sl_multiplier",
                "risk_reward", "entry_timestamp", "exit_timestamp", "entry_price",
                "exit_price", "trade_return", "equity", "roc"
            ])
        return pd.DataFrame([asdict(r) for r in self.records])

    @classmethod
    def from_dataframe(cls, symbol: str, df: pd.DataFrame) -> "EquityData":
        """Reconstructs EquityData state from a pandas DataFrame."""
        if df is None or df.empty:
            return cls(symbol=symbol, records=[])
        
        records = []
        for _, row in df.iterrows():
            records.append(EquityRecord(
                method_id=str(row["method_id"]),
                symbol=str(row["symbol"]),
                timeframe=str(row["timeframe"]),
                strategy=str(row["strategy"]),
                sl_multiplier=float(row["sl_multiplier"]),
                risk_reward=float(row["risk_reward"]),
                entry_timestamp=str(row["entry_timestamp"]),
                exit_timestamp=str(row["exit_timestamp"]),
                entry_price=float(row["entry_price"]),
                exit_price=float(row["exit_price"]),
                trade_return=float(row["trade_return"]),
                equity=float(row["equity"]),
                roc=float(row["roc"])
            ))
        return cls(symbol=symbol, records=records)

# ==============================================================================
# ========= End: 6.1 Equity Data Model =========================================
# ==============================================================================


# ==============================================================================
# ========= Start: 6.2 Equity Data Loading & Tracking =========================
# ==============================================================================

def get_latest_method_states(equity_data: EquityData, methods: List[Method]) -> Dict[str, Dict[str, Any]]:
    """
    Establishes the starting state for each method from existing stock equity data.
    If a method has no prior history, it initializes with starting equity and zero ROC.
    """
    starting_eq = getattr(config, "STARTING_EQUITY", 100.0)
    method_map = {get_method_id(m): m for m in methods}
    states: Dict[str, Dict[str, Any]] = {}
    
    # Initialize defaults
    for m_id, method_obj in method_map.items():
        states[m_id] = {
            "method": method_obj,
            "equity": starting_eq,
            "roc": 0.0,
            "last_exit_timestamp": None,
            "equity_history": [starting_eq]
        }
        
    if not equity_data or not equity_data.records:
        return states

    # Parse through existing records chronologically
    for record in equity_data.records:
        m_id = record.method_id
        if m_id in states:
            states[m_id]["equity"] = record.equity
            states[m_id]["roc"] = record.roc
            states[m_id]["last_exit_timestamp"] = record.exit_timestamp
            states[m_id]["equity_history"].append(record.equity)

    return states


def get_latest_exit_timestamp(equity_data: EquityData, methods: Optional[List[Method]] = None) -> Optional[str]:
    """
    Finds the earliest exit timestamp among all methods to safely determine 
     historical simulation start bounds.
    """
    if not equity_data or not equity_data.records:
        return None

    if methods is None:
        latest_timestamps = [r.exit_timestamp for r in equity_data.records if r.exit_timestamp]
        return max(latest_timestamps) if latest_timestamps else None

    valid_method_ids = {get_method_id(m) for m in methods}
    timestamps = [
        r.exit_timestamp for r in equity_data.records 
        if r.method_id in valid_method_ids and r.exit_timestamp
    ]
    
    return min(timestamps) if len(timestamps) == len(valid_method_ids) else None

# ==============================================================================
# ========= End: 6.2 Equity Data Loading & Tracking ===========================
# ==============================================================================


# ==============================================================================
# ========= Start: 6.3 Calculations ===========================================
# ==============================================================================

def apply_trade_to_equity(previous_equity: float, trade_return: float) -> float:
    """Updates method equity based on relative trade return."""
    return previous_equity * (1.0 + trade_return)


def calculate_equity_roc(equity_history: List[float], period: int = getattr(config, "ROC_PERIOD", 30)) -> float:
    """Calculates Rate of Change (ROC) on the method's historical equity curve."""
    if len(equity_history) <= 1:
        return 0.0
    
    current_equity = equity_history[-1]
    
    if len(equity_history) > period:
        past_equity = equity_history[-(period + 1)]
    else:
        past_equity = equity_history[0]
        
    if past_equity <= 0:
        return 0.0
        
    return ((current_equity - past_equity) / past_equity) * 100.0

# ==============================================================================
# ========= End: 6.3 Calculations ==============================================
# ==============================================================================


# ==============================================================================
# ========= Start: 6.4 Equity Integration Interfaces ==========================
# ==============================================================================

def update_equity_curves(
    existing_equity: EquityData,
    new_trades: List[Dict[str, Any]]
) -> EquityData:
    """
    Integrates newly completed simulation trades into existing equity curve structures.
    """
    if not new_trades:
        return existing_equity

    symbol = existing_equity.symbol
    records = list(existing_equity.records)
    
    # Map method histories
    history_map: Dict[str, List[float]] = {}
    latest_equity: Dict[str, float] = {}
    
    starting_eq = getattr(config, "STARTING_EQUITY", 100.0)
    roc_period = getattr(config, "ROC_PERIOD", 30)

    for r in records:
        if r.method_id not in history_map:
            history_map[r.method_id] = [starting_eq]
        history_map[r.method_id].append(r.equity)
        latest_equity[r.method_id] = r.equity

    sorted_trades = sorted(new_trades, key=lambda x: str(x.get("exit_timestamp", "")))

    for trade in sorted_trades:
        m_id = str(trade["method_id"])
        prev_eq = latest_equity.get(m_id, starting_eq)
        
        if "trade_return" in trade:
            t_return = float(trade["trade_return"])
        else:
            entry_p = float(trade["entry_price"])
            exit_p = float(trade["exit_price"])
            t_return = (exit_p - entry_p) / entry_p if entry_p != 0 else 0.0

        new_eq = apply_trade_to_equity(prev_eq, t_return)
        
        if m_id not in history_map:
            history_map[m_id] = [starting_eq]
        history_map[m_id].append(new_eq)
        latest_equity[m_id] = new_eq

        roc_val = calculate_equity_roc(history_map[m_id], period=roc_period)

        rec = EquityRecord(
            method_id=m_id,
            symbol=symbol,
            timeframe=str(trade.get("timeframe", "")),
            strategy=str(trade.get("strategy", "")),
            sl_multiplier=float(trade.get("sl_multiplier", 0.0)),
            risk_reward=float(trade.get("risk_reward", 0.0)),
            entry_timestamp=str(trade.get("entry_timestamp", "")),
            exit_timestamp=str(trade.get("exit_timestamp", "")),
            entry_price=float(trade.get("entry_price", 0.0)),
            exit_price=float(trade.get("exit_price", 0.0)),
            trade_return=t_return,
            equity=new_eq,
            roc=roc_val
        )
        records.append(rec)

    return EquityData(symbol=symbol, records=records)


def update_stock_equity(
    symbol: str,
    existing_equity_data: EquityData,
    market_data: Dict[str, Any],
    methods: List[Method]
) -> Tuple[EquityData, Dict[str, float]]:
    """
    Primary API function for updating historical equity curves and retrieving ROC state maps.
    """
    method_states = get_latest_method_states(existing_equity_data, methods)
    
    cutoffs = {m_id: state["last_exit_timestamp"] for m_id, state in method_states.items()}
    new_completed_trades = simulation.run_simulation(
        market_data=market_data,
        methods=methods,
        cutoffs=cutoffs
    )
    
    updated_equity_data = update_equity_curves(existing_equity_data, new_completed_trades)
    
    # Re-extract latest ROC values for downstream allocation modules
    final_states = get_latest_method_states(updated_equity_data, methods)
    latest_rocs = {m_id: state["roc"] for m_id, state in final_states.items()}

    return updated_equity_data, latest_rocs

# ==============================================================================
# ========= End: 6.4 Equity Interface ==========================================
# ==============================================================================