"""
equity.py
=========
Type: Core Module
Purpose: Manages equity curve updates, method performance tracking, 
         in-flight active position state, and rate-of-change (ROC) 
         calculations per stock and method.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
import pandas as pd

# Internal Architecture Imports
import config
from methods import Method, get_method_id
import simulation


@dataclass
class EquityRecord:
    """Standardized data container representing a completed or active trade."""
    method_id: str
    symbol: str
    timeframe: str
    strategy: str
    sl_multiplier: float
    risk_reward: float
    entry_timestamp: str
    exit_timestamp: Optional[str]
    entry_price: float
    exit_price: float
    trade_return: float
    equity: float
    roc: float

    @property
    def is_active(self) -> bool:
        """Returns True if the trade is currently active/open."""
        return not self.exit_timestamp or str(self.exit_timestamp).strip().lower() in ("", "none", "nan", "nat")


class EquityData:
    """State container for all method equity records for a specific stock."""
    
    def __init__(self, symbol: str, records: Optional[List[EquityRecord]] = None):
        self.symbol = symbol
        self.records: List[EquityRecord] = records if records is not None else []

    def to_dataframe(self) -> pd.DataFrame:
        """Converts internal equity records into a Parquet-ready DataFrame."""
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
            exit_ts = row.get("exit_timestamp")
            if pd.isna(exit_ts) or str(exit_ts).strip().lower() in ("none", "nan", "nat", ""):
                exit_ts_str = None
            else:
                exit_ts_str = str(exit_ts)

            records.append(EquityRecord(
                method_id=str(row["method_id"]),
                symbol=str(row.get("symbol", symbol)),
                timeframe=str(row["timeframe"]),
                strategy=str(row["strategy"]),
                sl_multiplier=float(row["sl_multiplier"]),
                risk_reward=float(row["risk_reward"]),
                entry_timestamp=str(row["entry_timestamp"]),
                exit_timestamp=exit_ts_str,
                entry_price=float(row["entry_price"]),
                exit_price=float(row.get("exit_price", 0.0)),
                trade_return=float(row.get("trade_return", 0.0)),
                equity=float(row.get("equity", getattr(config, "STARTING_EQUITY", 100.0))),
                roc=float(row.get("roc", 0.0))
            ))
        return cls(symbol=symbol, records=records)


def _parse_timestamp(ts: Union[str, datetime]) -> Optional[datetime]:
    """Parses various timestamp inputs into UTC-aware datetime objects."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts.astimezone(timezone.utc) if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    
    ts_str = str(ts).strip()
    if not ts_str or ts_str.lower() in ("none", "nan", "nat"):
        return None
        
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            dt = pd.to_datetime(ts_str).to_pydatetime()
            return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None


def get_latest_method_states(equity_data: EquityData, methods: List[Method]) -> Dict[str, Dict[str, Any]]:
    starting_eq = getattr(config, "STARTING_EQUITY", 100.0)
    method_map = {get_method_id(m): m for m in methods}
    states: Dict[str, Dict[str, Any]] = {}
    
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

    for record in equity_data.records:
        m_id = record.method_id
        if m_id in states:
            states[m_id]["equity"] = record.equity
            states[m_id]["roc"] = record.roc
            if record.exit_timestamp:
                states[m_id]["last_exit_timestamp"] = record.exit_timestamp
            states[m_id]["equity_history"].append(record.equity)

    return states


def get_latest_exit_timestamp(
    equity_data: EquityData, 
    methods: Optional[List[Method]] = None
) -> Optional[datetime]:
    if not equity_data or not equity_data.records:
        return None

    valid_method_ids = {get_method_id(m) for m in methods} if methods is not None else None
    timestamps: List[datetime] = []

    for r in equity_data.records:
        if r.exit_timestamp and not r.is_active:
            if valid_method_ids is None or r.method_id in valid_method_ids:
                dt = _parse_timestamp(r.exit_timestamp)
                if dt is not None:
                    timestamps.append(dt)
    
    return max(timestamps) if timestamps else None


def get_earliest_active_trade_timestamp(
    equity_data: EquityData, 
    methods: Optional[List[Method]] = None
) -> Optional[datetime]:
    if not equity_data or not equity_data.records:
        return None

    valid_method_ids = {get_method_id(m) for m in methods} if methods is not None else None
    active_entry_timestamps: List[datetime] = []

    for r in equity_data.records:
        if r.is_active:
            if valid_method_ids is None or r.method_id in valid_method_ids:
                dt = _parse_timestamp(r.entry_timestamp)
                if dt is not None:
                    active_entry_timestamps.append(dt)

    return min(active_entry_timestamps) if active_entry_timestamps else None


def apply_trade_to_equity(previous_equity: float, trade_return: float) -> float:
    return previous_equity * (1.0 + trade_return)


def calculate_equity_roc(equity_history: List[float], period: int = getattr(config, "ROC_PERIOD", 30)) -> float:
    if len(equity_history) <= 1:
        return 0.0
    
    current_equity = equity_history[-1]
    past_equity = equity_history[-(period + 1)] if len(equity_history) > period else equity_history[0]
        
    if past_equity <= 0:
        return 0.0
        
    return ((current_equity - past_equity) / past_equity) * 100.0


def update_equity_curves(
    existing_equity: EquityData,
    new_trades: List[Dict[str, Any]]
) -> EquityData:
    if not new_trades:
        return existing_equity

    symbol = existing_equity.symbol
    records = list(existing_equity.records)
    
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
            entry_p = float(trade.get("entry_price", 0.0))
            exit_p = float(trade.get("exit_price", 0.0))
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
            exit_timestamp=str(trade.get("exit_timestamp", "")) if trade.get("exit_timestamp") else None,
            entry_price=float(trade.get("entry_price", 0.0)),
            exit_price=float(trade.get("exit_price", 0.0)),
            trade_return=t_return,
            equity=new_eq,
            roc=roc_val
        )
        records.append(rec)

    return EquityData(symbol=symbol, records=records)