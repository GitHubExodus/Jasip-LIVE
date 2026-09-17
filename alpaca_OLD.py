"""
alpaca.py - Thin execution API wrapper for Alpaca Trading.

This module isolates all direct communication with Alpaca REST APIs, handling order
submission, cancellations, order/position queries, bracket orders, and extraction of 
actual execution prices/timestamps for downstream processing.
"""

import math
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    LimitOrderRequest,
    MarketOrderRequest,
    TakeProfitRequest,
    StopLossRequest,
    GetOrdersRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus, QueryOrderStatus
from alpaca.common.exceptions import APIError

import config

logger = logging.getLogger(__name__)


# ========= Start: 9.1 Alpaca Connection =============
class AlpacaConnection:
    """
    Maintains and provides the trading client connection using parameters from config.py.
    Isolation layer for Alpaca credentials and SDK communication errors.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        paper: Optional[bool] = None
    ):
        self.api_key = api_key or getattr(config, "ALPACA_API_KEY", "")
        self.secret_key = secret_key or getattr(config, "ALPACA_SECRET_KEY", "")
        self.paper = paper if paper is not None else getattr(config, "ALPACA_PAPER", True)
        self._client: Optional[TradingClient] = None

    def connect(self) -> TradingClient:
        """Initializes and returns the Alpaca TradingClient instance."""
        if self._client is None:
            try:
                self._client = TradingClient(
                    api_key=self.api_key,
                    secret_key=self.secret_key,
                    paper=self.paper
                )
                logger.info(f"Connected to Alpaca API (Paper: {self.paper})")
            except Exception as e:
                logger.error(f"Failed to connect to Alpaca Trading Client: {e}")
                raise
        return self._client

    @property
    def client(self) -> TradingClient:
        """Property wrapper to ensure client exists upon access."""
        if self._client is None:
            return self.connect()
        return self._client


# Lazy connection getter to avoid global initialization side-effects
_connection: Optional[AlpacaConnection] = None

def get_client() -> TradingClient:
    """Helper function to retrieve the active Alpaca client instance safely."""
    global _connection
    if _connection is None:
        _connection = AlpacaConnection()
    return _connection.client
# ========= End: 9.1 Alpaca Connection =============


# ========= Helper Utility =============
def _get_enum_value(enum_or_str: Any) -> str:
    """Helper to safely extract string value from Alpaca Enum or plain string."""
    if hasattr(enum_or_str, "value"):
        return str(enum_or_str.value)
    return str(enum_or_str)


# ========= Start: 9.2 Order Submission =============
def submit_order(
    symbol: str,
    qty: float,
    side: str,
    order_type: str = "limit",
    limit_price: Optional[float] = None,
    time_in_force: str = "gtc"
) -> Dict[str, Any]:
    """
    Submits a simple order (Limit or Market) to Alpaca. Does NOT contain trading strategy decisions.
    
    Returns:
        Dict normalized order summary: {"order_id": str, "status": str, "symbol": str, "qty": float}
    """
    client = get_client()
    side_enum = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
    tif_enum = TimeInForce.GTC if time_in_force.lower() == "gtc" else TimeInForce.DAY

    try:
        if order_type.lower() == "limit":
            if limit_price is None:
                raise ValueError("limit_price must be provided for limit orders.")
            req = LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=side_enum,
                time_in_force=tif_enum,
                limit_price=round(float(limit_price), 2)
            )
        else:
            req = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=side_enum,
                time_in_force=tif_enum
            )

        order = client.submit_order(order_data=req)
        logger.info(f"Submitted {order_type} order {order.id} for {qty} shares of {symbol}")
        
        return {
            "order_id": str(order.id),
            "status": _get_enum_value(order.status),
            "symbol": str(order.symbol),
            "qty": float(order.qty),
            "created_at": order.created_at
        }
    except APIError as e:
        logger.error(f"Alpaca API error on order submission for {symbol}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error submitting order for {symbol}: {e}")
        raise
# ========= End: 9.2 Order Submission =============


# ========= Start: 9.3 Order Cancellation =============
def cancel_order(order_id: str) -> Dict[str, Any]:
    """
    Cancels an existing order by ID.
    
    Returns:
        Dict cancellation result: {"order_id": str, "cancelled": bool, "message": str}
    """
    client = get_client()
    try:
        client.cancel_order_by_id(order_id)
        logger.info(f"Successfully cancelled order {order_id}")
        return {"order_id": str(order_id), "cancelled": True, "message": "Cancelled"}
    except APIError as e:
        # Gracefully handle orders that are already cancelled or filled
        logger.warning(f"Failed to cancel order {order_id}: {e}")
        return {"order_id": str(order_id), "cancelled": False, "message": str(e)}
    except Exception as e:
        logger.error(f"Unexpected error cancelling order {order_id}: {e}")
        return {"order_id": str(order_id), "cancelled": False, "message": str(e)}
# ========= End: 9.3 Order Cancellation =============


# ========= Start: 9.4 Order / Position Queries =============
def get_open_orders(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves current open orders, optionally filtered by stock symbol."""
    client = get_client()
    req = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol] if symbol else None)
    
    try:
        orders = client.get_orders(filter=req)
        return [
            {
                "order_id": str(o.id),
                "symbol": str(o.symbol),
                "side": _get_enum_value(o.side),
                "qty": float(o.qty),
                "filled_qty": float(o.filled_qty) if o.filled_qty is not None else 0.0,
                "limit_price": float(o.limit_price) if o.limit_price is not None else None,
                "status": _get_enum_value(o.status),
                "order_type": _get_enum_value(o.type),
                "client_order_id": str(o.client_order_id) if o.client_order_id else "",
                "created_at": o.created_at
            }
            for o in orders
        ]
    except Exception as e:
        logger.error(f"Error querying open orders: {e}")
        return []


def get_positions(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves active portfolio positions, optionally filtered by symbol."""
    client = get_client()
    try:
        if symbol:
            try:
                p = client.get_open_position(symbol)
                positions = [p]
            except APIError:
                return []
        else:
            positions = client.get_all_positions()

        return [
            {
                "symbol": str(p.symbol),
                "qty": float(p.qty),
                "entry_price": float(p.avg_entry_price),
                "current_price": float(p.current_price) if p.current_price is not None else 0.0,
                "market_value": float(p.market_value) if p.market_value is not None else 0.0,
                "unrealized_pl": float(p.unrealized_pl) if p.unrealized_pl is not None else 0.0
            }
            for p in positions
        ]
    except Exception as e:
        logger.error(f"Error querying open positions: {e}")
        return []


def get_order_by_id(order_id: str) -> Optional[Dict[str, Any]]:
    """Fetches details for a specific order by ID."""
    client = get_client()
    try:
        o = client.get_order_by_id(order_id)
        legs = []
        if getattr(o, "legs", None):
            legs = [str(leg.id) for leg in o.legs if hasattr(leg, "id")]

        return {
            "order_id": str(o.id),
            "symbol": str(o.symbol),
            "status": _get_enum_value(o.status),
            "side": _get_enum_value(o.side),
            "qty": float(o.qty),
            "filled_qty": float(o.filled_qty) if o.filled_qty is not None else 0.0,
            "filled_avg_price": float(o.filled_avg_price) if o.filled_avg_price else None,
            "legs": legs,
            "created_at": o.created_at,
            "filled_at": o.filled_at
        }
    except Exception as e:
        logger.error(f"Error fetching order {order_id}: {e}")
        return None
# ========= End: 9.4 Order / Position Queries =============


# ========= Start: 9.5 Bracket Order Handling =============
def create_bracket_order(
    symbol: str,
    qty: float,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    client_order_id: Optional[str] = None,
    time_in_force: str = "gtc"
) -> Dict[str, Any]:
    """
    Submits a complete non-expiring Bracket Order structure (Entry Limit + Stop Loss + Take Profit) to Alpaca.
    Prices are rounded to two decimals to comply with standard exchange pricing bounds.
    """
    client = get_client()
    tif_enum = TimeInForce.GTC if time_in_force.lower() == "gtc" else TimeInForce.DAY

    req = LimitOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide.BUY,
        time_in_force=tif_enum,
        limit_price=round(float(entry_price), 2),
        take_profit=TakeProfitRequest(limit_price=round(float(take_profit), 2)),
        stop_loss=StopLossRequest(stop_price=round(float(stop_loss), 2)),
        client_order_id=client_order_id
    )

    try:
        order = client.submit_order(order_data=req)
        logger.info(
            f"Submitted Bracket Order {order.id} for {symbol} | "
            f"Entry: {entry_price:.2f}, SL: {stop_loss:.2f}, TP: {take_profit:.2f}"
        )
        
        legs = []
        if getattr(order, "legs", None):
            legs = [str(leg.id) for leg in order.legs if hasattr(leg, "id")]

        return {
            "order_id": str(order.id),
            "symbol": str(order.symbol),
            "status": _get_enum_value(order.status),
            "qty": float(order.qty),
            "legs": legs,
            "created_at": order.created_at
        }
    except APIError as e:
        logger.error(f"Alpaca API error on bracket order creation for {symbol}: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to submit bracket order for {symbol}: {e}")
        raise
# ========= End: 9.5 Bracket Order Handling =============


# ========= Start: 9.6 Completed Trade Retrieval =============
def get_completed_trade(entry_order_id: str) -> Optional[Dict[str, Any]]:
    """
    Queries Alpaca to construct official execution info for a completed bracket trade.
    Uses Alpaca as the source of truth for filled entry and exit prices and timestamps.
    """
    client = get_client()
    try:
        parent_order = client.get_order_by_id(entry_order_id)
        if _get_enum_value(parent_order.status).lower() != "filled":
            return None

        # Check nested child legs (Take Profit / Stop Loss)
        legs = getattr(parent_order, "legs", None)
        if not legs:
            return None

        filled_exit_leg = None
        for leg in legs:
            leg_id = getattr(leg, "id", leg)
            try:
                leg_order = client.get_order_by_id(leg_id)
                if _get_enum_value(leg_order.status).lower() == "filled":
                    filled_exit_leg = leg_order
                    break
            except Exception as leg_err:
                logger.warning(f"Could not retrieve leg {leg_id}: {leg_err}")
                continue

        if not filled_exit_leg:
            return None

        entry_time = (
            parent_order.filled_at.isoformat()
            if getattr(parent_order, "filled_at", None)
            else (parent_order.created_at.isoformat() if getattr(parent_order, "created_at", None) else None)
        )
        
        exit_time = (
            filled_exit_leg.filled_at.isoformat()
            if getattr(filled_exit_leg, "filled_at", None)
            else (filled_exit_leg.created_at.isoformat() if getattr(filled_exit_leg, "created_at", None) else None)
        )

        return {
            "symbol": str(parent_order.symbol),
            "entry_price": float(parent_order.filled_avg_price),
            "entry_timestamp": entry_time,
            "exit_price": float(filled_exit_leg.filled_avg_price),
            "exit_timestamp": exit_time,
            "qty": float(parent_order.filled_qty),
            "entry_order_id": str(parent_order.id),
            "exit_order_id": str(filled_exit_leg.id)
        }
    except Exception as e:
        logger.error(f"Error fetching completed trade execution for order {entry_order_id}: {e}")
        return None
# ========= End: 9.6 Completed Trade Retrieval =============


# ========= Start: 9.7 Share Quantity Calculation =============
def calculate_shares(allocation_dollars: float, current_share_price: float) -> int:
    """
    Converts capital allocation dollars into whole integer share counts using mathematical floor.
    
    Formula:
        shares = floor(allocation_dollars / current_share_price)
    """
    if current_share_price <= 0 or allocation_dollars <= 0:
        return 0
    return math.floor(allocation_dollars / current_share_price)
# ========= End: 9.7 Share Quantity Calculation =============


# ========= Start: 9.8 Alpaca Interface =============
class AlpacaInterface:
    """
    Public standard interface wrapping all Alpaca API operations into a unified interface
    preventing direct Alpaca SDK dependency leakage throughout live.py or morning.py.
    """

    def __init__(self):
        self.conn = AlpacaConnection()

    def submit_order(self, symbol: str, qty: float, side: str, order_type: str = "limit", limit_price: Optional[float] = None) -> Dict[str, Any]:
        return submit_order(symbol, qty, side, order_type, limit_price)

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        return cancel_order(order_id)

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        return get_open_orders(symbol)

    def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        return get_positions(symbol)

    def get_order_by_id(self, order_id: str) -> Optional[Dict[str, Any]]:
        return get_order_by_id(order_id)

    def create_bracket_order(
        self,
        symbol: str,
        qty: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        client_order_id: Optional[str] = None
    ) -> Dict[str, Any]:
        return create_bracket_order(symbol, qty, entry_price, stop_loss, take_profit, client_order_id)

    def get_completed_trade(self, entry_order_id: str) -> Optional[Dict[str, Any]]:
        return get_completed_trade(entry_order_id)

    def calculate_shares(self, allocation_dollars: float, current_share_price: float) -> int:
        return calculate_shares(allocation_dollars, current_share_price)
# ========= End: 9.8 Alpaca Interface =============