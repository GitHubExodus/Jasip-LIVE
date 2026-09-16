"""
live.py - Live Trading Application Orchestrator

Runs the live trading session throughout the market day, maintaining
real-time market data, incremental indicator calculations, order flow,
and active trade monitoring via the Alpaca API.
"""

from datetime import datetime
import logging
import math
import time
import zoneinfo

import alpaca
import config
import contributions
import data
import indicators
from methods import get_method_id, Method
import strategy

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("LiveOrchestrator")


# ==============================================================================
# ========= Start: 11.1 Live Initialization ====================================
# ==============================================================================
def initialize_live_session(starting_capital: float) -> dict:
    """Prepare all state, connectivity, and indicators required before trading begins."""
    ny_tz = zoneinfo.ZoneInfo(config.TIMEZONE)
    current_time_ny = datetime.now(ny_tz)

    logger.info("Initializing Alpaca API client...")
    alpaca_client = alpaca.connect()

    logger.info("Loading contribution allocations and tradeable methods...")
    contribution_data = contributions.load_contributions()
    top_methods = contributions.get_tradeable_methods(
        contribution_data, max_methods=getattr(config, "MAX_TRADE_METHODS", 10)
    )

    if not top_methods:
        logger.warning("No eligible tradeable methods returned from contributions.")

    # Identify unique symbols across eligible top methods
    active_symbols = list({method.symbol for method in top_methods})
    logger.info(f"Active symbol universe ({len(active_symbols)}): {active_symbols}")

    market_datasets = {}
    indicator_states = {}

    for symbol in active_symbols:
        logger.info(f"Initializing market data and indicators for {symbol}...")
        # Load historical bars dictionary containing '5m', '30m', and '1d' dataset wrappers
        bars_dict = data.initialize_stock(symbol)
        market_datasets[symbol] = bars_dict

        # Initialize incremental indicator states per timeframe
        indicator_states[symbol] = {
            tf: indicators.initialize_indicators(bars_dict[tf])
            for tf in config.TIMEFRAMES
        }

    # Recover existing positions/orders from Alpaca (Source of Truth)
    logger.info("Recovering open positions and pending orders from Alpaca...")
    open_positions = alpaca.get_positions(alpaca_client)
    open_orders = alpaca.get_open_orders(alpaca_client)

    active_method_trades = {}
    for method in top_methods:
        method_id = get_method_id(method)
        trade_state = alpaca.reconstruct_method_trade_state(
            alpaca_client, method, open_positions, open_orders
        )
        if trade_state:
            active_method_trades[method_id] = trade_state
            logger.info(f"Recovered trade state for method {method_id}: {trade_state['status']}")

    return {
        "start_time": current_time_ny,
        "alpaca_client": alpaca_client,
        "starting_capital": starting_capital,
        "top_methods": top_methods,
        "contribution_data": contribution_data,
        "market_datasets": market_datasets,
        "indicator_states": indicator_states,
        "active_method_trades": active_method_trades,
    }
# ==============================================================================
# ====== End: 11.1 Live Initialization =========================================
# ==============================================================================


# ==============================================================================
# ========= Start: 11.2 Capital & Method Setup ================================
# ==============================================================================
def calculate_method_allocations(
    starting_capital: float,
    top_methods: list[Method],
    contribution_data: dict
) -> dict[str, dict]:
    """Establish fixed daily capital allocations using helper mapping functions."""
    allocations = {}
    
    # Extract allocation weights map using contributions framework helper
    weight_map = contributions.get_method_weights(contribution_data)

    for method in top_methods:
        method_id = get_method_id(method)
        weight = weight_map.get(method_id, 0.0)
        allocated_dollars = starting_capital * weight

        allocations[method_id] = {
            "method": method,
            "contribution": weight,
            "allocated_dollars": allocated_dollars,
        }
        logger.info(f"Allocation -> Method: {method_id} | Weight: {weight:.2%} | Capital: ${allocated_dollars:,.2f}")

    return allocations


def calculate_share_quantity(allocated_dollars: float, current_price: float) -> int:
    """Calculate integer share count using available capital allocation."""
    if current_price <= 0 or allocated_dollars <= 0:
        return 0
    return math.floor(allocated_dollars / current_price)
# ==============================================================================
# ====== End: 11.2 Capital & Method Setup ======================================
# ==============================================================================


# ==============================================================================
# ========= Start: 11.3 Market Data & Indicator Updates =======================
# ==============================================================================
def update_market_and_indicators(
    alpaca_client,
    symbols: list[str],
    market_datasets: dict,
    indicator_states: dict,
) -> None:
    """Fetch latest bar ticks, update bar wrappers in place, and increment indicators."""
    for symbol in symbols:
        latest_bars = data.get_latest_bars(alpaca_client, symbol)

        # Update 5m and 30m dataset objects in place
        data.update_bars(market_datasets[symbol]["5m"], latest_bars["5m"])
        data.update_bars(market_datasets[symbol]["30m"], latest_bars["30m"])

        # Update daily timeframe wrapper in place using revised 30m data
        updated_daily_df = data.build_daily_bars(market_datasets[symbol]["30m"])
        data.update_bars(market_datasets[symbol]["1d"], updated_daily_df)

        # Incrementally update indicator states using latest bar methods
        for tf in config.TIMEFRAMES:
            current_bar = market_datasets[symbol][tf].latest()
            indicator_states[symbol][tf] = indicators.update_indicators(
                previous_state=indicator_states[symbol][tf],
                current_bar=current_bar,
            )
# ==============================================================================
# ====== End: 11.3 Market Data & Indicator Updates ============================
# ==============================================================================


# ==============================================================================
# ========= Start: 11.4 Method Processing =====================================
# ==============================================================================
def process_eligible_methods(
    alpaca_client,
    top_methods: list[Method],
    allocations: dict,
    market_datasets: dict,
    indicator_states: dict,
    active_method_trades: dict,
) -> None:
    """Evaluate and route every eligible method independently."""
    for method in top_methods:
        method_id = get_method_id(method)
        symbol = method.symbol
        timeframe = method.timeframe

        current_bar = market_datasets[symbol][timeframe].latest()
        current_price = current_bar.close
        ind_state = indicator_states[symbol][timeframe]

        if method_id in active_method_trades:
            monitor_active_trade(
                alpaca_client=alpaca_client,
                method_id=method_id,
                active_method_trades=active_method_trades,
            )
        else:
            manage_entry_order(
                alpaca_client=alpaca_client,
                method=method,
                allocation=allocations[method_id]["allocated_dollars"],
                current_price=current_price,
                indicator_state=ind_state,
                active_method_trades=active_method_trades,
            )
# ==============================================================================
# ====== End: 11.4 Method Processing ==========================================
# ==============================================================================


# ==============================================================================
# ========= Start: 11.5 Entry Order Management ================================
# ==============================================================================
def manage_entry_order(
    alpaca_client,
    method: Method,
    allocation: float,
    current_price: float,
    indicator_state,
    active_method_trades: dict,
) -> None:
    """Calculate target crossover price, validate entry range, and avoid cancellation churn."""
    method_id = get_method_id(method)

    crossover_price = strategy.calculate_crossover_price(
        fast_period=method.fast_ema,
        slow_period=method.slow_ema,
        indicator_state=indicator_state,
    )

    is_valid_range = strategy.is_entry_valid(
        current_price=current_price,
        crossover_price=crossover_price,
        green_avg=indicator_state.green_avg,
        red_avg=indicator_state.red_avg,
        range_multiplier=config.ENTRY_RANGE_MULTIPLIER,
    )

    existing_trade = active_method_trades.get(method_id)

    if is_valid_range:
        trade_levels = strategy.calculate_trade_levels(
            entry_price=crossover_price,
            red_avg=indicator_state.red_avg,
            sl_multiplier=method.sl_multiplier,
            risk_reward=method.risk_reward,
        )

        # Skip order re-submission if existing waiting order's entry price is still accurate
        if existing_trade and existing_trade.get("status") == "WAITING_ENTRY":
            current_target = existing_trade.get("target_price")
            if current_target and math.isclose(current_target, trade_levels.entry_price, rel_tol=1e-4):
                return  # Keep order alive without canceling

        # Target shifted or no order exists: cancel outdated pending order
        alpaca.cancel_waiting_entry_order(alpaca_client, method)

        shares = calculate_share_quantity(
            allocated_dollars=allocation, current_price=crossover_price
        )

        if shares > 0:
            order_result = alpaca.create_bracket_order(
                client=alpaca_client,
                symbol=method.symbol,
                shares=shares,
                entry_price=trade_levels.entry_price,
                stop_loss=trade_levels.stop_loss,
                take_profit=trade_levels.take_profit,
            )

            if order_result and order_result.get("order_id"):
                active_method_trades[method_id] = {
                    "status": "WAITING_ENTRY",
                    "order_id": order_result["order_id"],
                    "target_price": trade_levels.entry_price,
                    "method": method,
                }
                logger.info(f"Submitted bracket entry for {method_id} @ ${trade_levels.entry_price:.2f}")
    else:
        # Out of range: cancel any existing pending order
        if existing_trade and existing_trade.get("status") == "WAITING_ENTRY":
            alpaca.cancel_waiting_entry_order(alpaca_client, method)
            del active_method_trades[method_id]
# ==============================================================================
# ====== End: 11.5 Entry Order Management ======================================
# ==============================================================================


# ==============================================================================
# ========= Start: 11.6 Active Trade Monitoring ===============================
# ==============================================================================
def monitor_active_trade(
    alpaca_client, method_id: str, active_method_trades: dict
) -> None:
    """Query Alpaca API to monitor the state of an existing order/position."""
    trade_info = active_method_trades.get(method_id)
    if not trade_info:
        return

    order_id = trade_info.get("order_id")
    if not order_id:
        return

    order_status = alpaca.get_order_status(alpaca_client, order_id)

    if getattr(order_status, "is_completed", False):
        handle_completed_trade(
            alpaca_client=alpaca_client,
            method_id=method_id,
            completed_order_id=order_id,
            active_method_trades=active_method_trades,
        )
    elif getattr(order_status, "is_filled", False):
        active_method_trades[method_id]["status"] = "IN_POSITION"
# ==============================================================================
# ====== End: 11.6 Active Trade Monitoring =====================================
# ==============================================================================


# ==============================================================================
# ========= Start: 11.7 Trade Completion Handling =============================
# ==============================================================================
def handle_completed_trade(
    alpaca_client,
    method_id: str,
    completed_order_id: str,
    active_method_trades: dict,
) -> None:
    """Retrieve actual executed trade metrics upon completion and release method state."""
    logger.info(f"Trade completed for method {method_id}. Order ID: {completed_order_id}")
    alpaca.get_completed_trade_details(alpaca_client, completed_order_id)
    del active_method_trades[method_id]
# ==============================================================================
# ====== End: 11.7 Trade Completion Handling ===================================
# ==============================================================================


# ==============================================================================
# ========= Start: 11.8 Live Interface / Main Loop ============================
# ==============================================================================
def run_live_loop() -> None:
    """Main application loop executing every tick during market hours."""
    try:
        starting_capital = float(input("Enter starting trading capital ($): "))
    except ValueError:
        logger.error("Invalid starting capital entered. Exiting.")
        return

    session = initialize_live_session(starting_capital)

    alpaca_client = session["alpaca_client"]
    top_methods = session["top_methods"]
    contribution_data = session["contribution_data"]
    market_datasets = session["market_datasets"]
    indicator_states = session["indicator_states"]
    active_method_trades = session["active_method_trades"]

    allocations = calculate_method_allocations(starting_capital, top_methods, contribution_data)
    active_symbols = list({method.symbol for method in top_methods})

    logger.info(
        f"Live session started with ${starting_capital:,.2f} capital across {len(top_methods)} methods."
    )

    try:
        while True:
            loop_start_time = time.time()

            # Check market open state via Alpaca API helper
            if not alpaca.is_market_open(alpaca_client):
                logger.info("US Equity market is currently closed. Standing by...")
                time.sleep(60)
                continue

            # Execute main tick sequence during active market hours
            update_market_and_indicators(
                alpaca_client=alpaca_client,
                symbols=active_symbols,
                market_datasets=market_datasets,
                indicator_states=indicator_states,
            )

            process_eligible_methods(
                alpaca_client=alpaca_client,
                top_methods=top_methods,
                allocations=allocations,
                market_datasets=market_datasets,
                indicator_states=indicator_states,
                active_method_trades=active_method_trades,
            )

            elapsed = time.time() - loop_start_time
            poll_interval = getattr(config, "POLL_INTERVAL_SECONDS", 60)
            sleep_duration = max(0.0, poll_interval - elapsed)
            time.sleep(sleep_duration)

    except KeyboardInterrupt:
        logger.info("Live trading session terminated by operator.")


if __name__ == "__main__":
    run_live_loop()
# ==============================================================================
# ====== End: 11.8 Live Interface / Main Loop ==================================
# ==============================================================================