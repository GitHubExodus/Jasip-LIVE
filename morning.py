"""
morning.py
==========
Type: Orchestration Script
Purpose: Pre-market application that executes the historical equity update process,
         ranks method performances, calculates allocations, and updates global storage.

Execution Sequence:
1. Load System Configuration
2. Load Universe Methods
3. Load & Initialize Equity Curves & In-Flight Active Positions
4. Progress Tracking & Historical Data Retrieval (with Indicator Buffer Padding)
5. Historical Simulation Execution
6. Equity Curve & ROC Updates
7. Global Contribution Calculation & Ranking
8. Cloud Storage Persistence with Exception Safeguards
"""

from datetime import datetime, timedelta, timezone
import logging
from typing import Dict, List, Any, Optional

# Core Architecture Imports
import config
from methods import (
    generate_methods,
    get_method_id,
    Method
)
from storage import (
    load_equity,
    save_equity,
    load_contributions,
    save_contributions
)
from data import initialize_stock, DataManager
from simulation import run_historical_simulation
from equity import (
    get_latest_exit_timestamp,
    get_earliest_active_trade_timestamp,
    update_equity_curves,
    EquityData
)
from contributions import (
    calculate_contributions,
    rank_methods,
    select_top_methods,
    build_contribution_record
)

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("MorningUpdater")

LOOKBACK_BUFFER_DAYS = getattr(config, "LOOKBACK_BUFFER_DAYS", 90)


def resolve_simulation_start_time(equity_data: EquityData, methods: List[Method]) -> datetime:
    """
    Determines starting timestamp for data retrieval and backtesting.
    Checks for in-flight/open trades first, falls back to the latest completed trade exit,
    or defaults to LOOKBACK_BUFFER_DAYS ago for fresh starts.
    """
    # 1. Active open trade check
    active_trade_time = get_earliest_active_trade_timestamp(equity_data, methods)
    if active_trade_time is not None:
        logger.info(f"Active in-flight position detected. Resuming simulation from: {active_trade_time}")
        return active_trade_time

    # 2. Historical trade exit check
    latest_exit = get_latest_exit_timestamp(equity_data, methods)
    if latest_exit is not None:
        return latest_exit

    # 3. Default Fallback for Fresh Start (e.g. 365 days lookback)
    default_days = getattr(config, "INITIAL_BACKTEST_DAYS", 365)
    fallback_time = datetime.now(timezone.utc) - timedelta(days=default_days)
    logger.info(f"No existing equity history found. Initializing fresh start from {default_days} days ago ({fallback_time.strftime('%Y-%m-%d')}).")
    return fallback_time

def run_morning_update() -> None:
    """Main orchestration sequence for the pre-market equity update pipeline."""
    
    # Part 10.1 Morning Initialization
    logger.info("Initializing Morning Update Process...")
    ny_now = datetime.now(timezone.utc).astimezone(config.TIMEZONE)
    logger.info(f"Current System Time (America/New_York): {ny_now}")
    
    symbols: List[str] = getattr(config, "SYMBOLS", ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"])
    logger.info(f"Target Symbol Universe ({len(symbols)}): {symbols}")

    # Part 10.2 Stock Loop & Progress Tracking
    all_updated_equity: Dict[str, EquityData] = {}

    for symbol in symbols:
        logger.info(f"--- Processing Stock: {symbol} ---")
        
        try:
            equity_data: EquityData = load_equity(symbol)
        except Exception as e:
            logger.warning(f"Failed to load equity data for {symbol} ({e}). Initializing fresh curve.")
            equity_data = EquityData(symbol=symbol)

        stock_methods: List[Method] = generate_methods(
            symbol=symbol,
            timeframes=config.TIMEFRAMES,
            strategies=getattr(config, "STRATEGIES", ("ema_cross",)),
            sl_multipliers=config.SL_MULTIPLIERS,
            risk_rewards=config.RISK_REWARD_VALUES
        )
        logger.info(f"Generated {len(stock_methods)} method combinations for {symbol}.")

        start_sim_time = resolve_simulation_start_time(equity_data, stock_methods)
        logger.info(f"Simulation reference timestamp for {symbol}: {start_sim_time or 'None (Fresh Start)'}")

        # Part 10.3 Historical Data Fetching & Backtest Simulation
        logger.info(f"Downloading historical market data for {symbol} starting from {start_sim_time}...")
        
        try:
            market_data: DataManager = initialize_stock(
                symbol=symbol,
                start_time=start_sim_time
            )

            completed_trades = run_historical_simulation(
                market_data=market_data,
                methods=stock_methods,
                start_time=start_sim_time
            )
            logger.info(f"Simulation generated {len(completed_trades)} new completed trades for {symbol}.")
        except Exception as e:
            logger.error(f"Error during market data/simulation execution for {symbol}: {e}")
            completed_trades = []

        # Part 10.4 Equity Curve Updates & Persistence
        logger.info(f"Updating equity curves for {symbol}...")
        updated_equity_data: EquityData = update_equity_curves(
            existing_equity=equity_data,
            new_trades=completed_trades
        )
        
        try:
            save_equity(symbol=symbol, equity_data=updated_equity_data)
            logger.info(f"Successfully saved equity updates to storage for {symbol}.")
        except Exception as e:
            logger.error(f"Failed to save equity updates for {symbol}: {e}")

        all_updated_equity[symbol] = updated_equity_data

    # Part 10.5 Global Contribution Calculation & Ranking
    logger.info("--- Executing Global Performance Ranking & Allocation ---")
    try:
        contribution_dataset = calculate_contributions(all_updated_equity)
        ranked_methods = rank_methods(contribution_dataset)
        top_methods = select_top_methods(
            ranked_methods=ranked_methods,
            limit=config.MAX_TRADE_METHODS
        )
        logger.info(f"Selected Top {len(top_methods)} eligible trade methods for live execution.")
    except Exception as e:
        logger.error(f"Error during contribution calculation and ranking: {e}")
        return

    # Part 10.6 Contribution Persistence
    logger.info("Persisting global contribution state and historical snapshots...")
    try:
        existing_contributions = load_contributions()
        updated_contributions = build_contribution_record(
            existing_contributions=existing_contributions,
            current_contributions=contribution_dataset,
            timestamp=ny_now
        )
        save_contributions(updated_contributions)
        logger.info("Global contribution history saved successfully.")
    except Exception as e:
        logger.error(f"Failed to persist contribution state: {e}")

    logger.info("==================================================")
    logger.info("MORNING UPDATE PROCESS COMPLETED SUCCESSFULLY.")
    logger.info("==================================================")


if __name__ == "__main__":
    run_morning_update()