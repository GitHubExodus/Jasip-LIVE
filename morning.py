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

# Indicator lookback buffer to prevent cold-start distortion (50 bars on 1d / max TF)
INDICATOR_LOOKBACK_BUFFER_DAYS = getattr(config, "LOOKBACK_BUFFER_DAYS", 90)


def resolve_simulation_start_time(equity_data: EquityData, methods: List[Method]) -> Optional[datetime]:
    """
    Determines the correct starting timestamp for historical data retrieval & backtesting.
    Checks for open/in-flight trades first to prevent re-entry duplicates; falls back to
    the latest completed trade exit timestamp.
    """
    # 1. Check if any methods currently have an active/unclosed trade
    active_trade_time = get_earliest_active_trade_timestamp(equity_data, methods)
    if active_trade_time is not None:
        logger.info(f"Active in-flight position detected. Simulation starting from open entry: {active_trade_time}")
        return active_trade_time

    # 2. Fall back to the latest completed exit timestamp across methods
    latest_exit = get_latest_exit_timestamp(equity_data, methods)
    return latest_exit


def run_morning_update() -> None:
    """Main orchestration sequence for the pre-market equity update pipeline."""
    
    # ========= Start: Part 10.1 Morning Initialization =============
    logger.info("Initializing Morning Update Process...")
    ny_now = datetime.now(timezone.utc).astimezone(config.TIMEZONE)
    logger.info(f"Current System Time (America/New_York): {ny_now}")
    
    # Load targets from universe configuration
    symbols: List[str] = config.SYMBOLS if hasattr(config, "SYMBOLS") else ["AAPL", "MSFT", "NVDA", "TSLA", "AMD"]
    logger.info(f"Target Symbol Universe ({len(symbols)}): {symbols}")
    # ========= End: Part 10.1 Morning Initialization =======

    # ========= Start: Part 10.2 Stock Loop & Progress Tracking =============
    all_updated_equity: Dict[str, EquityData] = {}

    for symbol in symbols:
        logger.info(f"--- Processing Stock: {symbol} ---")
        
        # Load existing equity curves from persistent storage
        try:
            equity_data: EquityData = load_equity(symbol)
        except Exception as e:
            logger.warning(f"Failed to load equity data for {symbol} ({e}). Initializing fresh curve.")
            equity_data = EquityData(symbol=symbol)

        # Generate all standardized strategy method combinations for this stock
        stock_methods: List[Method] = generate_methods(
            symbol=symbol,
            timeframes=config.TIMEFRAMES,
            strategies=getattr(config, "STRATEGIES", ("ema_cross",)),
            sl_multipliers=config.SL_MULTIPLIERS,
            risk_rewards=config.RISK_REWARD_VALUES
        )
        logger.info(f"Generated {len(stock_methods)} method combinations for {symbol}.")

        # Determine exact starting timestamp considering both active and closed trades
        sim_start_time = resolve_simulation_start_time(equity_data, stock_methods)
        logger.info(f"Simulation reference timestamp for {symbol}: {sim_start_time or 'None (Fresh Start)'}")
        # ========= End: Part 10.2 Stock Loop & Progress Tracking =======

        # ========= Start: Part 10.3 Historical Simulation Execution =============
        # Apply indicator lookback buffer padding to prevent cold-start indicator distortion
        if sim_start_time is not None:
            data_fetch_start = sim_start_time - timedelta(days=INDICATOR_LOOKBACK_BUFFER_DAYS)
        else:
            data_fetch_start = None

        logger.info(f"Downloading historical market data for {symbol} (Buffer Start: {data_fetch_start})...")
        
        try:
            market_data: DataManager = initialize_stock(
                symbol=symbol,
                start_time=data_fetch_start
            )
        except Exception as e:
            logger.error(f"Failed to fetch market data for {symbol}: {e}. Skipping symbol.", exc_info=True)
            continue

        logger.info(f"Executing historical bar simulation for {symbol} across {len(stock_methods)} methods...")
        
        # Run historical backtest simulation starting strictly from sim_start_time
        completed_trades = run_historical_simulation(
            market_data=market_data,
            methods=stock_methods,
            start_time=sim_start_time
        )
        logger.info(f"Simulation generated {len(completed_trades)} new completed trades for {symbol}.")
        # ========= End: Part 10.3 Historical Simulation Execution =======

        # ========= Start: Part 10.4 Equity Curve & ROC Updates =============
        logger.info(f"Updating equity curves and calculating method ROCs for {symbol}...")
        
        # Integrate simulation results into the stock's master equity dataset
        updated_equity_data: EquityData = update_equity_curves(
            existing_equity=equity_data,
            new_trades=completed_trades
        )
        
        # Safe storage persistence with exception boundaries
        try:
            save_equity(symbol=symbol, equity_data=updated_equity_data)
            logger.info(f"Successfully saved equity updates to storage for {symbol}.")
        except Exception as e:
            logger.error(f"Critical error persisting equity data for {symbol}: {e}", exc_info=True)

        # Store updated equity data in memory for global contribution calculations
        all_updated_equity[symbol] = updated_equity_data
        # ========= End: Part 10.4 Equity Curve & ROC Updates =======

    # Check if any stocks were processed successfully before global ranking
    if not all_updated_equity:
        logger.critical("No stock equity datasets were updated. Aborting global allocation calculation.")
        return

    # ========= Start: Part 10.5 Global Contribution & Ranking =============
    logger.info("--- Executing Global Performance Ranking & Allocation ---")
    
    # Calculate ROC and performance allocations across the ENTIRE universe of stocks and methods
    contribution_dataset = calculate_contributions(all_updated_equity)
    
    # Rank methods globally based on positive ROC contribution
    ranked_methods = rank_methods(contribution_dataset)
    
    # Select top tradeable methods (max limit defined in config.MAX_TRADE_METHODS)
    top_methods = select_top_methods(
        ranked_methods=ranked_methods,
        limit=getattr(config, "MAX_TRADE_METHODS", 10)
    )
    logger.info(f"Selected Top {len(top_methods)} eligible trade methods for live execution.")
    # ========= End: Part 10.5 Global Contribution & Ranking =======

    # ========= Start: Part 10.6 Contribution Persistence =============
    logger.info("Persisting global contribution state and historical snapshots...")
    
    try:
        existing_contributions = load_contributions()
    except Exception as e:
        logger.warning(f"Could not load historical contributions ({e}). Starting fresh record.")
        existing_contributions = None

    # Build updated snapshot containing current ROC, rank, and contribution % for every method
    updated_contributions = build_contribution_record(
        existing_contributions=existing_contributions,
        current_contributions=contribution_dataset,
        timestamp=ny_now
    )
    
    # Save unified contribution snapshot back to Cloud storage
    try:
        save_contributions(updated_contributions)
        logger.info("Global contribution history saved successfully.")
    except Exception as e:
        logger.critical(f"Failed to persist global contribution state to storage: {e}", exc_info=True)
    # ========= End: Part 10.6 Contribution Persistence =======

    logger.info("==================================================")
    logger.info("MORNING UPDATE PROCESS COMPLETED SUCCESSFULLY.")
    logger.info("==================================================")


if __name__ == "__main__":
    run_morning_update()