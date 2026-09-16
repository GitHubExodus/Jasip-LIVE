# main.py

import os
import time
from datetime import datetime, timezone

from old2.config import (
    MARKET_DATA_START_DATE,
    R2_PATHS,
)

from old2.data_storage import (
    load_text,
    load_parquet,
    parquet_exists,
)

from old2.market_data import (
    create_data_client,
    download_5m_data,
    get_next_candle_time,
)

from old2.methods import (
    generate_all_methods,
)

from old2.system_state import (
    create_system_state,
)

from old2.indicator_state import (
    initialize_indicator_state,
)

from old2.timeframe_data import (
    update_all_timeframes,
)

from old2.strategies import (
    calculate_strategy,
)

from old2.equity_curves import (
    create_equity_curve,
    dataframe_to_equity_curves,
)

from old2.simulator import (
    create_method_simulator_state,
)

from old2.alpaca_trading import (
    create_trading_client,
)

from old2.tick_processor import (
    refresh_contribution_state,
    update_symbol_timeframes,
    update_symbol_indicators,
    update_symbol_strategies,
    process_tick,
)


# ============================================================
# PATHS
# ============================================================

STOCK_SYMBOLS_PATH = "misc/symbols.txt"


# ============================================================
# LOAD SYMBOLS
# ============================================================

def load_symbols():
    """
    Load stock symbols from R2 misc/symbols.txt.

    Expected format:

        AAPL
        AMD
        NVDA
        MSFT
    """

    text = load_text(STOCK_SYMBOLS_PATH)

    symbols = []

    for line in text.splitlines():

        symbol = line.strip().upper()

        if not symbol:
            continue

        symbols.append(symbol)

    return symbols


# ============================================================
# LOAD EQUITY CURVES
# ============================================================

def load_existing_equity_curves(state):
    """
    Load the shared equity-curve Parquet from R2.

    Returns:
        True if existing data was loaded.
        False if no data exists.
    """

    path = R2_PATHS["equity_curves"]

    if not parquet_exists(path):
        return False

    equity_data = load_parquet(path)

    if equity_data is None or equity_data.empty:
        return False

    state["equity_curves"] = (
        dataframe_to_equity_curves(
            equity_data
        )
    )

    return True


# ============================================================
# LOAD CONTRIBUTION HISTORY
# ============================================================

def load_existing_contributions(state):
    """
    Load the shared contribution history from R2.
    """

    path = R2_PATHS["contributions"]

    if not parquet_exists(path):
        return False

    contribution_data = load_parquet(path)

    if contribution_data is None or contribution_data.empty:
        return False

    state["contribution_data"] = contribution_data

    return True


# ============================================================
# INITIALIZE METHODS
# ============================================================

def initialize_methods(
    state,
    symbols,
):
    """
    Generate every method for every stock and place them
    into system state.
    """

    methods = generate_all_methods(symbols)

    for method in methods:

        method_id = method["method_id"]

        state["methods"][method_id] = method

    return methods


# ============================================================
# INITIALIZE SIMULATORS
# ============================================================

def initialize_simulators(
    state,
    methods,
):
    """
    Create one simulator state for every method.
    """

    for method in methods:

        method_id = method["method_id"]

        state["simulator_states"][method_id] = (
            create_method_simulator_state(
                method_id=method_id,
                symbol=method["symbol"],
            )
        )


# ============================================================
# INITIALIZE EQUITY CURVES
# ============================================================

def initialize_equity_curves(
    state,
    methods,
):
    """
    Create an empty equity curve only for methods that
    do not already have a restored curve.
    """

    for method in methods:

        method_id = method["method_id"]

        if method_id in state["equity_curves"]:
            continue

        state["equity_curves"][method_id] = (
            create_equity_curve(
                method_id=method_id,
                symbol=method["symbol"],
            )
        )


# ============================================================
# INITIALIZE HISTORICAL MARKET DATA
# ============================================================

def initialize_market_data(
    market_client,
    symbols,
):
    """
    Download historical 5m data for every symbol.
    """

    market_data = {}

    end = datetime.now(timezone.utc)

    for index, symbol in enumerate(symbols, start=1):

        print(
            f"[{index}/{len(symbols)}] "
            f"Downloading {symbol} 5m data..."
        )

        data = download_5m_data(
            client=market_client,
            symbol=symbol,
            start=MARKET_DATA_START_DATE,
            end=end,
        )

        if data is None or data.empty:

            print(
                f"  No data for {symbol}"
            )

            continue

        market_data[symbol] = data

        print(
            f"  Loaded {len(data):,} bars"
        )

    return market_data


# ============================================================
# INITIALIZE SYMBOL PROCESSING
# ============================================================

def initialize_symbol_processing(
    state,
    symbol,
    data_5m,
):
    """
    Build all timeframes and initialize indicators and
    strategies for one symbol.
    """

    # --------------------------------------------------------
    # Store raw 5m data
    # --------------------------------------------------------

    state["market_data"][symbol] = data_5m

    # --------------------------------------------------------
    # Build all timeframes
    # --------------------------------------------------------

    timeframe_data = update_symbol_timeframes(
        state=state,
        symbol=symbol,
        data_5m=data_5m,
    )

    # --------------------------------------------------------
    # Initialize indicators
    # --------------------------------------------------------

    update_symbol_indicators(
        state=state,
        symbol=symbol,
        timeframe_data=timeframe_data,
    )

    # --------------------------------------------------------
    # Calculate strategies
    # --------------------------------------------------------

    update_symbol_strategies(
        state=state,
        symbol=symbol,
        timeframe_data=timeframe_data,
    )


# ============================================================
# INITIALIZE SYSTEM
# ============================================================

def initialize_system(
    market_client,
    symbols,
):
    """
    Build the complete in-memory system state.
    """

    state = create_system_state()

    # --------------------------------------------------------
    # Methods
    # --------------------------------------------------------

    methods = initialize_methods(
        state,
        symbols,
    )

    print(
        f"Created {len(methods):,} methods."
    )

    # --------------------------------------------------------
    # Restore equity curves
    # --------------------------------------------------------

    if load_existing_equity_curves(state):

        print(
            f"Loaded "
            f"{len(state['equity_curves']):,} "
            f"existing equity curves."
        )

    else:

        print(
            "No existing equity curves found."
        )

    # --------------------------------------------------------
    # Restore contribution history
    # --------------------------------------------------------

    if load_existing_contributions(state):

        print(
            "Loaded existing contribution history."
        )

    else:

        print(
            "No existing contribution history found."
        )

    # --------------------------------------------------------
    # Create missing equity curves
    # --------------------------------------------------------

    initialize_equity_curves(
        state,
        methods,
    )

    # --------------------------------------------------------
    # Initialize simulator states
    # --------------------------------------------------------

    initialize_simulators(
        state,
        methods,
    )

    # --------------------------------------------------------
    # Historical market data
    # --------------------------------------------------------

    market_data = initialize_market_data(
        market_client,
        symbols,
    )

    # --------------------------------------------------------
    # Build initial processing state
    # --------------------------------------------------------

    for symbol, data_5m in market_data.items():

        print(
            f"Initializing {symbol}..."
        )

        initialize_symbol_processing(
            state=state,
            symbol=symbol,
            data_5m=data_5m,
        )

    # --------------------------------------------------------
    # Calculate current contributions
    # --------------------------------------------------------
    #
    # IMPORTANT:
    #
    # We recalculate ROC from the restored equity curves.
    # We do not trust an old contribution ranking after
    # restarting the program.
    #

    current_timestamp = datetime.now(timezone.utc)

    refresh_contribution_state(
        state=state,
        timestamp=current_timestamp,
    )

    # --------------------------------------------------------
    # Mark initialized
    # --------------------------------------------------------

    state["initialized"] = True

    print(
        "System initialization complete."
    )

    return state


# ============================================================
# WAIT FOR NEXT CANDLE
# ============================================================

def wait_for_next_candle():
    """
    Wait until the next 5m candle is completed plus the
    configured confirmation delay.
    """

    now = datetime.now(timezone.utc)

    next_candle = get_next_candle_time(
        now
    )

    while True:

        current_time = datetime.now(timezone.utc)

        remaining = (
            next_candle - current_time
        ).total_seconds()

        if remaining <= 0:
            return

        time.sleep(
            min(remaining, 1.0)
        )


# ============================================================
# GET LATEST MARKET DATA
# ============================================================

def get_latest_market_data(
    market_client,
    symbol,
):
    """
    Download the newest available 5m bar for a symbol.
    """

    from old2.market_data import (
        download_latest_5m_bar,
    )

    now = datetime.now(timezone.utc)

    return download_latest_5m_bar(
        client=market_client,
        symbol=symbol,
        start=now,
        end=now,
    )


# ============================================================
# PROCESS ALL SYMBOLS
# ============================================================

def process_all_symbols(
    state,
    market_client,
    trading_client,
    symbols,
):
    """
    Process the newest market bar for every symbol.
    """

    for index, symbol in enumerate(
        symbols,
        start=1,
    ):

        try:

            new_data = get_latest_market_data(
                market_client=market_client,
                symbol=symbol,
            )

            if new_data is None or new_data.empty:

                print(
                    f"[{index}/{len(symbols)}] "
                    f"{symbol}: no new data"
                )

                continue

            process_tick(
                state=state,
                symbol=symbol,
                new_5m_data=new_data,
                trading_client=trading_client,
            )

            print(
                f"[{index}/{len(symbols)}] "
                f"{symbol}: processed"
            )

        except Exception as exc:

            print(
                f"[{index}/{len(symbols)}] "
                f"{symbol}: ERROR: {exc}"
            )


# ============================================================
# LIVE LOOP
# ============================================================

def run_live_loop(
    state,
    market_client,
    trading_client,
    symbols,
):
    """
    Continuously process completed 5m candles.
    """

    print(
        "Starting live trading loop..."
    )

    while True:

        try:

            # ------------------------------------------------
            # Wait for next completed 5m candle
            # ------------------------------------------------

            wait_for_next_candle()

            print(
                "\n"
                f"Processing candle at "
                f"{datetime.now(timezone.utc)}"
            )

            # ------------------------------------------------
            # Process every stock
            # ------------------------------------------------

            process_all_symbols(
                state=state,
                market_client=market_client,
                trading_client=trading_client,
                symbols=symbols,
            )

        except KeyboardInterrupt:

            print(
                "Trading system stopped."
            )

            break

        except Exception as exc:

            print(
                f"ERROR in live loop: {exc}"
            )

            time.sleep(5)


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "Starting trading system..."
    )

    # --------------------------------------------------------
    # API credentials
    # --------------------------------------------------------

    alpaca_api_key = os.environ[
        "ALPACA_API_KEY"
    ]

    alpaca_secret_key = os.environ[
        "ALPACA_SECRET_KEY"
    ]

    # --------------------------------------------------------
    # Alpaca clients
    # --------------------------------------------------------

    market_client = create_data_client(
        alpaca_api_key,
        alpaca_secret_key,
    )

    trading_client = create_trading_client(
        api_key=alpaca_api_key,
        secret_key=alpaca_secret_key,
        paper=True,
    )

    # --------------------------------------------------------
    # Symbols
    # --------------------------------------------------------

    symbols = load_symbols()

    print(
        f"Loaded {len(symbols):,} symbols."
    )

    # --------------------------------------------------------
    # Initialize entire system
    # --------------------------------------------------------

    state = initialize_system(
        market_client=market_client,
        symbols=symbols,
    )

    # --------------------------------------------------------
    # Start live processing
    # --------------------------------------------------------

    run_live_loop(
        state=state,
        market_client=market_client,
        trading_client=trading_client,
        symbols=symbols,
    )


# ============================================================
# PROGRAM ENTRY
# ============================================================

if __name__ == "__main__":
    main()