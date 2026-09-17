# ============================================================
# 1. INITIALIZE
# ============================================================

# ============================================================
# 1.1 LOAD CONFIGURATION
# ============================================================

from pathlib import Path
from zoneinfo import ZoneInfo


# ------------------------------------------------------------
# Time configuration
# ------------------------------------------------------------

TIMEZONE = ZoneInfo("America/New_York")

TIMEFRAMES = (
    "5m",
    "30m",
    "day",
)


# ------------------------------------------------------------
# Indicator configuration
# ------------------------------------------------------------

EMA_PERIODS = (
    3,
    5,
    9,
    14,
    21,
    30,
    50,
    100,
    200,
)

EMA_PAIRS = (
    (3, 5),
    (5, 9),
    (9, 14),
    (14, 21),
    (21, 30),
    (30, 50),
    (50, 100),
    (100, 200),
)

ROC_PERIOD = 30

CANDLE_AVERAGE_WINDOW = 200


# ------------------------------------------------------------
# Trading-method configuration
# ------------------------------------------------------------

SL_MULTIPLIERS = (
    1,
    2,
)

RISK_REWARD_RATIOS = (
    1,
    1.5,
    2,
    3,
    5,
)

STRATEGY_NAME = "ema_crossover"

ALLOW_SHORTS = False


# ------------------------------------------------------------
# Equity configuration
# ------------------------------------------------------------

STARTING_EQUITY = 100.0

DEFAULT_HISTORY_YEARS = 1


# ------------------------------------------------------------
# Historical simulation configuration
# ------------------------------------------------------------

# Market data is interpreted in America/New_York.
MARKET_TIMEZONE = "America/New_York"

# Extended-hours data is used for 5m and 30m.
INCLUDE_EXTENDED_HOURS = True

# Day bars are built from 30m data.
BUILD_DAY_FROM_30M = True

# If SL and TP occur in the same historical candle,
# the stop loss wins.
STOP_LOSS_WINS_SAME_CANDLE = True


# ------------------------------------------------------------
# R2 configuration
# ------------------------------------------------------------

R2_BUCKET_NAME = "stocks-data"

R2_EQUITY_PATH = "equity/"
R2_CONTRIBUTIONS_PATH = "contributions/"
R2_TOP_20_PATH = "top_methods/"

R2_SYMBOLS_PATH = "misc/symbols.txt"


# ------------------------------------------------------------
# Alpaca configuration
# ------------------------------------------------------------

# Alpaca is included in the configuration because the same
# overall system uses Alpaca for live trading.
ALPACA_PAPER = True

ALPACA_API_KEY = "PKA4A6THLEKI6QD2MQPOAO25J3"
ALPACA_SECRET_KEY = "4nj9w53vMrNKJGZsHqN7Siqy34z2Gis9TffWi2beszNU"


# ------------------------------------------------------------
# Other fixed settings
# ------------------------------------------------------------

# No fractional shares.
ALLOW_FRACTIONAL_SHARES = False

# Live polling interval. The historical process does not use
# this value, but it belongs to the shared fixed configuration.
LIVE_POLL_SECONDS = 60


# ------------------------------------------------------------
# Configuration validation
# ------------------------------------------------------------

if not TIMEFRAMES:
    raise ValueError("TIMEFRAMES cannot be empty")

if not EMA_PERIODS:
    raise ValueError("EMA_PERIODS cannot be empty")

if not EMA_PAIRS:
    raise ValueError("EMA_PAIRS cannot be empty")

if ROC_PERIOD <= 0:
    raise ValueError("ROC_PERIOD must be greater than 0")

if CANDLE_AVERAGE_WINDOW <= 0:
    raise ValueError("CANDLE_AVERAGE_WINDOW must be greater than 0")

if STARTING_EQUITY <= 0:
    raise ValueError("STARTING_EQUITY must be greater than 0")

if DEFAULT_HISTORY_YEARS <= 0:
    raise ValueError("DEFAULT_HISTORY_YEARS must be greater than 0")

if not SL_MULTIPLIERS:
    raise ValueError("SL_MULTIPLIERS cannot be empty")

if not RISK_REWARD_RATIOS:
    raise ValueError("RISK_REWARD_RATIOS cannot be empty")


# Verify that every EMA pair uses configured EMA periods.
for fast_period, slow_period in EMA_PAIRS:
    if fast_period not in EMA_PERIODS:
        raise ValueError(
            f"Fast EMA period {fast_period} is not configured"
        )

    if slow_period not in EMA_PERIODS:
        raise ValueError(
            f"Slow EMA period {slow_period} is not configured"
        )

    if fast_period >= slow_period:
        raise ValueError(
            f"EMA pair ({fast_period}, {slow_period}) "
            "must have fast EMA < slow EMA"
        )


# ============================================================
# END 1.1 LOAD CONFIGURATION
# ============================================================


# ============================================================
# 1.2 LOAD STOCK LIST
# ============================================================

def load_stock_list(symbols_file):
    """
    Load stock symbols from the symbols file.

    Each non-empty line represents one stock symbol.

    Returns:
        list[str]: Clean, unique stock symbols.
    """

    symbols_path = Path(symbols_file)

    if not symbols_path.exists():
        raise FileNotFoundError(
            f"Stock symbols file not found: {symbols_path}"
        )

    symbols = []

    with symbols_path.open("r", encoding="utf-8") as file:
        for line in file:
            symbol = line.strip().upper()

            # Ignore empty lines.
            if not symbol:
                continue

            symbols.append(symbol)

    # Remove duplicates while preserving the original order.
    symbols = list(dict.fromkeys(symbols))

    if not symbols:
        raise ValueError(
            f"No stock symbols found in: {symbols_path}"
        )

    return symbols


# ------------------------------------------------------------
# Load the stock list
# ------------------------------------------------------------

STOCK_SYMBOLS = load_stock_list(R2_SYMBOLS_PATH)


# ------------------------------------------------------------
# Validate the stock list
# ------------------------------------------------------------

for symbol in STOCK_SYMBOLS:
    if not symbol:
        raise ValueError("Stock symbol cannot be empty")

    if symbol != symbol.upper():
        raise ValueError(
            f"Stock symbol must be uppercase: {symbol}"
        )


# Number of stocks being processed.
STOCK_COUNT = len(STOCK_SYMBOLS)


# ============================================================
# END 1.2 LOAD STOCK LIST
# ============================================================





# ============================================================
# 1.3 LOAD EXISTING EQUITY DATA
# ============================================================

import io
import os

import boto3
import pandas as pd


# ------------------------------------------------------------
# R2 connection
# ------------------------------------------------------------

R2_ENDPOINT_URL = "https://98f8e959e677f16bddcf44f609fec6a0.r2.cloudflarestorage.com"
R2_ACCESS_KEY_ID = "00e18b0c16ecb3395cd6f7c8e0eb3554"
R2_SECRET_ACCESS_KEY = "33799355abaedc234309dbfbc80a2a66c3bfd856f0dcaecf0031e1fbcbcd84a0"


def create_r2_client():
    """
    Create the Cloudflare R2 client.
    """

    if not R2_ENDPOINT_URL:
        raise ValueError("R2_ENDPOINT_URL is not configured")

    if not R2_ACCESS_KEY_ID:
        raise ValueError("R2_ACCESS_KEY_ID is not configured")

    if not R2_SECRET_ACCESS_KEY:
        raise ValueError("R2_SECRET_ACCESS_KEY is not configured")

    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    )


R2_CLIENT = create_r2_client()


# ------------------------------------------------------------
# Equity data configuration
# ------------------------------------------------------------

R2_EQUITY_PATH = "equity"


def equity_object_key(symbol):
    """
    Return the R2 object key for one stock's shared equity file.

    All methods belonging to the stock are stored together.
    """

    return f"{R2_EQUITY_PATH}/{symbol}.parquet"


# ------------------------------------------------------------
# Load one stock's equity data
# ------------------------------------------------------------

def load_stock_equity(symbol):
    """
    Load the shared equity history for one stock.

    Returns:
        pandas.DataFrame:
            Existing equity history if found.

        None:
            If no equity file exists for the stock.
    """

    object_key = equity_object_key(symbol)

    try:
        response = R2_CLIENT.get_object(
            Bucket=R2_BUCKET_NAME,
            Key=object_key,
        )

    except R2_CLIENT.exceptions.NoSuchKey:
        return None

    except Exception as error:
        error_code = getattr(error, "response", {}).get(
            "Error", {}
        ).get("Code")

        if error_code in ("NoSuchKey", "404", "NotFound"):
            return None

        raise

    data = response["Body"].read()

    if not data:
        return None

    equity = pd.read_parquet(
        io.BytesIO(data)
    )

    if equity.empty:
        return None

    return equity


# ------------------------------------------------------------
# Load equity data for every stock
# ------------------------------------------------------------

EXISTING_EQUITY = {}

STOCKS_WITH_EQUITY = []
STOCKS_WITHOUT_EQUITY = []


for symbol in STOCK_SYMBOLS:

    equity = load_stock_equity(symbol)

    if equity is None:
        EXISTING_EQUITY[symbol] = pd.DataFrame()
        STOCKS_WITHOUT_EQUITY.append(symbol)

    else:
        EXISTING_EQUITY[symbol] = equity
        STOCKS_WITH_EQUITY.append(symbol)


# ------------------------------------------------------------
# Basic validation
# ------------------------------------------------------------

if (
    len(STOCKS_WITH_EQUITY)
    + len(STOCKS_WITHOUT_EQUITY)
    != STOCK_COUNT
):
    raise RuntimeError(
        "Equity loading did not produce a state for every stock"
    )


# ============================================================
# END 1.3 LOAD EXISTING EQUITY DATA
# ============================================================





# ============================================================
# 1.4 DETERMINE SIMULATION START POINTS
# ============================================================

from datetime import datetime, timedelta


def get_latest_equity_timestamp(equity):
    """
    Find the most recent completed-trade timestamp
    in a stock's equity history.

    The equity history is ordered by completed trade
    / exit timestamp.
    """

    if equity.empty:
        return None

    if "exit_timestamp" not in equity.columns:
        raise ValueError(
            "Equity data is missing 'exit_timestamp'"
        )

    timestamps = pd.to_datetime(
        equity["exit_timestamp"],
        utc=True,
        errors="coerce",
    )

    timestamps = timestamps.dropna()

    if timestamps.empty:
        return None

    return timestamps.max()


def get_default_simulation_start():
    """
    Return the default historical simulation start point.

    The configured default is approximately one year ago.
    """

    now = datetime.now(TIMEZONE)

    return now - timedelta(
        days=365 * DEFAULT_HISTORY_YEARS
    )


# ------------------------------------------------------------
# Determine simulation start for every stock
# ------------------------------------------------------------

SIMULATION_START_POINTS = {}

DEFAULT_START_STOCKS = []
EQUITY_START_STOCKS = []


for symbol in STOCK_SYMBOLS:

    equity = EXISTING_EQUITY[symbol]

    latest_exit_timestamp = get_latest_equity_timestamp(
        equity
    )

    if latest_exit_timestamp is not None:

        # Convert the UTC timestamp to the configured
        # America/New_York timezone.
        simulation_start = latest_exit_timestamp.tz_convert(
            TIMEZONE
        )

        SIMULATION_START_POINTS[symbol] = simulation_start
        EQUITY_START_STOCKS.append(symbol)

    else:

        simulation_start = get_default_simulation_start()

        SIMULATION_START_POINTS[symbol] = simulation_start
        DEFAULT_START_STOCKS.append(symbol)


# ------------------------------------------------------------
# Validate that every stock has a simulation start point
# ------------------------------------------------------------

if len(SIMULATION_START_POINTS) != STOCK_COUNT:
    raise RuntimeError(
        "A simulation start point was not created for every stock"
    )


# ============================================================
# END 1.4 DETERMINE SIMULATION START POINTS
# ============================================================









# ============================================================
# 1.5 INITIALIZE STOCK STATES
# ============================================================

from dataclasses import dataclass, field


@dataclass
class StockState:
    """
    In-memory state for one stock during the morning process.
    """

    symbol: str

    # Historical simulation start point.
    simulation_start: datetime

    # Existing equity history for this stock.
    equity_data: pd.DataFrame = field(
        default_factory=pd.DataFrame
    )

    # Filled by later stages.
    market_data: dict = field(
        default_factory=dict
    )

    indicator_state: dict = field(
        default_factory=dict
    )

    method_state: dict = field(
        default_factory=dict
    )

    simulation_state: dict = field(
        default_factory=dict
    )

    storage_state: dict = field(
        default_factory=dict
    )


# ------------------------------------------------------------
# Create stock states
# ------------------------------------------------------------

STOCK_STATES = {}


for symbol in STOCK_SYMBOLS:

    STOCK_STATES[symbol] = StockState(
        symbol=symbol,
        simulation_start=SIMULATION_START_POINTS[symbol],
        equity_data=EXISTING_EQUITY[symbol],
    )


# ------------------------------------------------------------
# Validate stock states
# ------------------------------------------------------------

if len(STOCK_STATES) != STOCK_COUNT:
    raise RuntimeError(
        "A stock state was not created for every stock"
    )


for symbol in STOCK_SYMBOLS:

    stock_state = STOCK_STATES[symbol]

    if stock_state.symbol != symbol:
        raise RuntimeError(
            f"Stock state symbol mismatch: {symbol}"
        )

    if stock_state.simulation_start is None:
        raise RuntimeError(
            f"Missing simulation start for {symbol}"
        )


# ============================================================
# END 1.5 INITIALIZE STOCK STATES
# ============================================================








# ============================================================
# 1.6 INITIALIZE METHOD STATES
# ============================================================

from dataclasses import dataclass


@dataclass
class MethodState:
    """
    In-memory state for one trading method.
    """

    method_id: str

    symbol: str
    timeframe: str
    strategy: str

    fast_ema: int
    slow_ema: int

    sl_multiplier: float
    risk_reward: float

    # --------------------------------------------------------
    # Trading state
    # --------------------------------------------------------

    active_trade: object = None

    # --------------------------------------------------------
    # Equity state
    # --------------------------------------------------------

    equity_reference: object = None
    current_roc: float = 0.0

    # --------------------------------------------------------
    # Simulation state
    # --------------------------------------------------------

    simulation_started: bool = False
    simulation_finished: bool = False


def create_method_id(
    symbol,
    timeframe,
    strategy,
    fast_ema,
    slow_ema,
    sl_multiplier,
    risk_reward,
):
    """
    Create the unique identifier for a method.
    """

    return (
        f"{symbol}|"
        f"{timeframe}|"
        f"{strategy}|"
        f"EMA{fast_ema}-{slow_ema}|"
        f"SL{sl_multiplier}|"
        f"RR{risk_reward}"
    )


def create_stock_methods(symbol):
    """
    Create every configured method for one stock.

    Returns:
        dict[str, MethodState]
    """

    methods = {}

    for timeframe in TIMEFRAMES:

        for fast_ema, slow_ema in EMA_PAIRS:

            for sl_multiplier in SL_MULTIPLIERS:

                for risk_reward in RISK_REWARD_RATIOS:

                    method_id = create_method_id(
                        symbol=symbol,
                        timeframe=timeframe,
                        strategy=STRATEGY_NAME,
                        fast_ema=fast_ema,
                        slow_ema=slow_ema,
                        sl_multiplier=sl_multiplier,
                        risk_reward=risk_reward,
                    )

                    if method_id in methods:
                        raise RuntimeError(
                            f"Duplicate method ID: {method_id}"
                        )

                    methods[method_id] = MethodState(
                        method_id=method_id,
                        symbol=symbol,
                        timeframe=timeframe,
                        strategy=STRATEGY_NAME,
                        fast_ema=fast_ema,
                        slow_ema=slow_ema,
                        sl_multiplier=sl_multiplier,
                        risk_reward=risk_reward,
                    )

    return methods


# ------------------------------------------------------------
# Create methods for every stock
# ------------------------------------------------------------

for symbol in STOCK_SYMBOLS:

    STOCK_STATES[symbol].method_state = (
        create_stock_methods(symbol)
    )


# ------------------------------------------------------------
# Validate method states
# ------------------------------------------------------------

METHODS_PER_STOCK = (
    len(TIMEFRAMES)
    * len(EMA_PAIRS)
    * len(SL_MULTIPLIERS)
    * len(RISK_REWARD_RATIOS)
)


for symbol in STOCK_SYMBOLS:

    methods = STOCK_STATES[symbol].method_state

    if len(methods) != METHODS_PER_STOCK:
        raise RuntimeError(
            f"{symbol} has {len(methods)} methods, "
            f"expected {METHODS_PER_STOCK}"
        )


# ============================================================
# END 1.6 INITIALIZE METHOD STATES
# ============================================================









# ============================================================
# 1.7 INITIALIZE SIMULATION STATE
# ============================================================

@dataclass
class SimulationState:
    """
    In-memory state for the historical simulation of one stock.
    """

    # --------------------------------------------------------
    # Time
    # --------------------------------------------------------

    current_timestamp: datetime = None

    # --------------------------------------------------------
    # Active and completed trades
    # --------------------------------------------------------

    active_trades: dict = field(
        default_factory=dict
    )

    completed_trades: list = field(
        default_factory=list
    )

    # --------------------------------------------------------
    # Market-data position
    # --------------------------------------------------------

    next_bar_position: dict = field(
        default_factory=dict
    )

    # --------------------------------------------------------
    # Simulation status
    # --------------------------------------------------------

    started: bool = False
    completed: bool = False


# ------------------------------------------------------------
# Create simulation state for every stock
# ------------------------------------------------------------

for symbol in STOCK_SYMBOLS:

    STOCK_STATES[symbol].simulation_state = SimulationState()


# ------------------------------------------------------------
# Validate simulation states
# ------------------------------------------------------------

for symbol in STOCK_SYMBOLS:

    simulation_state = (
        STOCK_STATES[symbol].simulation_state
    )

    if simulation_state.started:
        raise RuntimeError(
            f"{symbol} simulation should not be started yet"
        )

    if simulation_state.completed:
        raise RuntimeError(
            f"{symbol} simulation should not be completed yet"
        )


# ============================================================
# END 1.7 INITIALIZE SIMULATION STATE
# ============================================================













# ============================================================
# 1.8 INITIALIZE STORAGE STATE
# ============================================================

@dataclass
class StorageState:
    """
    In-memory storage state for the morning process.
    """

    # --------------------------------------------------------
    # R2 connection
    # --------------------------------------------------------

    r2_client: object = None

    bucket_name: str = R2_BUCKET_NAME

    # --------------------------------------------------------
    # Existing data
    # --------------------------------------------------------

    equity_data: dict = field(
        default_factory=dict
    )

    # --------------------------------------------------------
    # Morning-process output
    # --------------------------------------------------------

    contribution_data: object = None

    top_20_data: object = None

    # --------------------------------------------------------
    # Storage status
    # --------------------------------------------------------

    connected: bool = False
    outputs_saved: bool = False


# ------------------------------------------------------------
# Create the global storage state
# ------------------------------------------------------------

STORAGE_STATE = StorageState(
    r2_client=R2_CLIENT,
    bucket_name=R2_BUCKET_NAME,
    equity_data=EXISTING_EQUITY,
    connected=True,
)


# ------------------------------------------------------------
# Connect stock states to storage state
# ------------------------------------------------------------

for symbol in STOCK_SYMBOLS:

    STOCK_STATES[symbol].storage_state = {
        "storage": STORAGE_STATE,
        "equity": EXISTING_EQUITY[symbol],
    }


# ------------------------------------------------------------
# Validate storage state
# ------------------------------------------------------------

if STORAGE_STATE.r2_client is None:
    raise RuntimeError(
        "R2 client was not initialized"
    )

if not STORAGE_STATE.bucket_name:
    raise RuntimeError(
        "R2 bucket name is missing"
    )

if not STORAGE_STATE.connected:
    raise RuntimeError(
        "R2 storage state is not connected"
    )


# ============================================================
# END 1.8 INITIALIZE STORAGE STATE
# ============================================================





















































# ============================================================
# 2. LOAD DATA
# ============================================================


# ============================================================
# 2.1 DETERMINE REQUIRED HISTORICAL RANGE
# ============================================================

def determine_required_historical_range(
    simulation_start: datetime,
) -> tuple[datetime, datetime]:
    """
    Determine the historical data range required for one stock.

    The simulation start is the point where historical
    simulation begins.

    Additional history is requested before the simulation
    start so the largest indicator windows can be initialized.

    Required indicator windows:
        - EMA 200
        - ROC 30
        - Green candle average 200
        - Red candle average 200

    The largest required window is 200 bars.

    A one-year lookback is used as a practical initialization
    buffer so that enough bars are available across all
    timeframes, especially the larger timeframes.

    The returned end timestamp is the simulation start.

    Parameters
    ----------
    simulation_start : datetime
        Stock-level simulation start timestamp.

    Returns
    -------
    tuple[datetime, datetime]
        (historical_start, historical_end)
    """

    if simulation_start.tzinfo is None:
        simulation_start = simulation_start.replace(tzinfo=TIMEZONE)
    else:
        simulation_start = simulation_start.astimezone(TIMEZONE)

    historical_start = simulation_start - timedelta(
        days=365 * DEFAULT_HISTORY_YEARS
    )

    historical_end = simulation_start

    return historical_start, historical_end


def determine_stock_data_ranges() -> dict[str, dict[str, datetime]]:
    """
    Determine the required historical data range for every stock.

    Each stock gets its own range because each stock can have a
    different simulation start point.

    Returns
    -------
    dict
        Structure:

        {
            "AAPL": {
                "start": datetime,
                "end": datetime
            },
            "MU": {
                "start": datetime,
                "end": datetime
            }
        }
    """

    data_ranges: dict[str, dict[str, datetime]] = {}

    for symbol in STOCK_SYMBOLS:
        simulation_start = SIMULATION_START_POINTS[symbol]

        historical_start, historical_end = (
            determine_required_historical_range(
                simulation_start
            )
        )

        data_ranges[symbol] = {
            "start": historical_start,
            "end": historical_end,
        }

    return data_ranges


REQUIRED_DATA_RANGES = determine_stock_data_ranges()


# ============================================================
# END 2.1
# ============================================================










# ============================================================
# 2.2 REQUEST 5m DATA
# ============================================================

import os

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

import numpy as np


def create_alpaca_data_client() -> StockHistoricalDataClient:
    """
    Create the Alpaca historical market-data client.

    API credentials are read from environment variables:

        APCA_API_KEY_ID
        APCA_API_SECRET_KEY
    """

    api_key = "PKA4A6THLEKI6QD2MQPOAO25J3"
    api_secret = "4nj9w53vMrNKJGZsHqN7Siqy34z2Gis9TffWi2beszNU"

    if not api_key:
        raise RuntimeError(
            "Missing APCA_API_KEY_ID environment variable."
        )

    if not api_secret:
        raise RuntimeError(
            "Missing APCA_API_SECRET_KEY environment variable."
        )

    return StockHistoricalDataClient(
        api_key=api_key,
        secret_key=api_secret,
    )


ALPACA_DATA_CLIENT = create_alpaca_data_client()


def request_5m_data() -> dict:
    """
    Request historical 5-minute stock bars for all stocks.

    The requested range is determined independently for each
    stock from REQUIRED_DATA_RANGES.

    Alpaca's multi-symbol endpoint requires one common
    start/end range per request, so stocks are grouped by
    compatible date ranges.

    Extended-hours data is requested by not applying a
    regular-market-hours filter.

    Returns
    -------
    dict
        Raw Alpaca response data grouped by stock symbol.

        {
            "AAPL": ...,
            "MU": ...,
            "TSLA": ...
        }
    """

    if not STOCK_SYMBOLS:
        return {}

    # --------------------------------------------------------
    # Group stocks by identical requested historical range.
    # --------------------------------------------------------

    range_groups: dict[tuple[datetime, datetime], list[str]] = {}

    for symbol in STOCK_SYMBOLS:
        data_range = REQUIRED_DATA_RANGES[symbol]

        start = data_range["start"]
        end = data_range["end"]

        range_key = (start, end)

        if range_key not in range_groups:
            range_groups[range_key] = []

        range_groups[range_key].append(symbol)

    # --------------------------------------------------------
    # Request data.
    # --------------------------------------------------------

    raw_data: dict[str, list] = {
        symbol: []
        for symbol in STOCK_SYMBOLS
    }

    for (start, end), symbols in range_groups.items():

        request = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame(
                5,
                TimeFrameUnit.Minute,
            ),
            start=start,
            end=end,
            feed="sip",
            adjustment="raw",
        )

        response = ALPACA_DATA_CLIENT.get_stock_bars(request)

        # ----------------------------------------------------
        # The SDK response is converted to a symbol -> bars
        # mapping. Each stock keeps its own shared 5m series.
        # ----------------------------------------------------

        for symbol in symbols:
            symbol_bars = response.data.get(symbol, [])

            raw_data[symbol].extend(symbol_bars)

    return raw_data


RAW_5M_DATA = request_5m_data()


# ============================================================
# END 2.2
# ============================================================





# ============================================================
# 2.3 REQUEST 30m DATA
# ============================================================

def request_30m_data() -> dict:
    """
    Request historical 30-minute stock bars for all stocks.

    Uses the same stock-specific historical ranges determined
    in Step 2.1.

    Extended-hours data is included because no regular-session
    filter is applied.

    Returns
    -------
    dict
        Raw Alpaca response data grouped by stock symbol.

        {
            "AAPL": [...],
            "MU": [...],
            "TSLA": [...]
        }
    """

    if not STOCK_SYMBOLS:
        return {}

    # --------------------------------------------------------
    # Group stocks that have the same requested date range.
    # --------------------------------------------------------

    range_groups: dict[tuple[datetime, datetime], list[str]] = {}

    for symbol in STOCK_SYMBOLS:
        data_range = REQUIRED_DATA_RANGES[symbol]

        start = data_range["start"]
        end = data_range["end"]

        range_key = (start, end)

        if range_key not in range_groups:
            range_groups[range_key] = []

        range_groups[range_key].append(symbol)

    # --------------------------------------------------------
    # Prepare output.
    # --------------------------------------------------------

    raw_data: dict[str, list] = {
        symbol: []
        for symbol in STOCK_SYMBOLS
    }

    # --------------------------------------------------------
    # Request 30-minute bars.
    # --------------------------------------------------------

    for (start, end), symbols in range_groups.items():

        request = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame(
                30,
                TimeFrameUnit.Minute,
            ),
            start=start,
            end=end,
            feed="sip",
            adjustment="raw",
        )

        response = ALPACA_DATA_CLIENT.get_stock_bars(request)

        # ----------------------------------------------------
        # Store each stock's bars in its shared 30m dataset.
        # ----------------------------------------------------

        for symbol in symbols:
            symbol_bars = response.data.get(symbol, [])

            raw_data[symbol].extend(symbol_bars)

    return raw_data


RAW_30M_DATA = request_30m_data()


# ============================================================
# END 2.3
# ============================================================








# ============================================================
# 2.4 LOAD 5m DATA
# ============================================================

def load_5m_data(raw_data: dict) -> dict[str, pd.DataFrame]:
    """
    Convert raw 5-minute Alpaca bars into DataFrames.

    One DataFrame is created per stock.

    The DataFrame is shared by every method using the 5m
    timeframe.

    No indicators are calculated here.
    """

    loaded_data: dict[str, pd.DataFrame] = {}

    for symbol in STOCK_SYMBOLS:

        bars = raw_data.get(symbol, [])

        if not bars:
            loaded_data[symbol] = pd.DataFrame(
                columns=[
                    "timestamp",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "trade_count",
                    "vwap",
                ]
            )
            continue

        rows = []

        for bar in bars:
            rows.append(
                (
                    bar.timestamp,
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.volume,
                    bar.trade_count,
                    bar.vwap,
                )
            )

        data = pd.DataFrame(
            rows,
            columns=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "trade_count",
                "vwap",
            ],
        )

        loaded_data[symbol] = data

    return loaded_data


LOADED_5M_DATA = load_5m_data(RAW_5M_DATA)


# ============================================================
# END 2.4
# ============================================================







# ============================================================
# 2.5 LOAD 30m DATA
# ============================================================

def load_30m_data(raw_data: dict) -> dict[str, pd.DataFrame]:
    """
    Convert raw 30-minute Alpaca bars into DataFrames.

    One DataFrame is created per stock.

    The DataFrame is shared by every method using the 30m
    timeframe.

    No indicators are calculated here.
    """

    loaded_data: dict[str, pd.DataFrame] = {}

    for symbol in STOCK_SYMBOLS:

        bars = raw_data.get(symbol, [])

        if not bars:
            loaded_data[symbol] = pd.DataFrame(
                columns=[
                    "timestamp",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "trade_count",
                    "vwap",
                ]
            )
            continue

        rows = []

        for bar in bars:
            rows.append(
                (
                    bar.timestamp,
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.volume,
                    bar.trade_count,
                    bar.vwap,
                )
            )

        data = pd.DataFrame(
            rows,
            columns=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "trade_count",
                "vwap",
            ],
        )

        loaded_data[symbol] = data

    return loaded_data


LOADED_30M_DATA = load_30m_data(RAW_30M_DATA)


# ============================================================
# END 2.5
# ============================================================





# ============================================================
# 2.6 BUILD DAY DATA FROM 30m DATA
# ============================================================

def build_day_data_from_30m(
    data_30m: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """
    Build daily OHLCV data from 30-minute data.

    Each New York calendar date becomes one daily bar.

    The daily bar includes:
        - Premarket
        - Regular market
        - After-hours

    No separate daily API request is made.

    This function only combines the existing 30m bars.
    Timestamp normalization and final data preparation
    belong to Step 3.
    """

    day_data: dict[str, pd.DataFrame] = {}

    for symbol in STOCK_SYMBOLS:

        data = data_30m.get(symbol)

        if data is None or data.empty:
            day_data[symbol] = pd.DataFrame(
                columns=[
                    "timestamp",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "trade_count",
                    "vwap",
                ]
            )
            continue

        data = data.copy()

        # ----------------------------------------------------
        # Alpaca timestamps are expected to be timezone-aware.
        #
        # Convert them to New York so the daily grouping is
        # based on the New York calendar date.
        # ----------------------------------------------------

        timestamps = pd.to_datetime(
            data["timestamp"],
            utc=True,
            errors="coerce",
        )

        data["timestamp"] = timestamps.dt.tz_convert(
            TIMEZONE
        )

        # ----------------------------------------------------
        # Remove rows whose timestamp could not be converted.
        # Full validation happens later in Step 2.7.
        # ----------------------------------------------------

        data = data.loc[
            data["timestamp"].notna()
        ].copy()

        if data.empty:
            day_data[symbol] = pd.DataFrame(
                columns=[
                    "timestamp",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "trade_count",
                    "vwap",
                ]
            )
            continue

        # ----------------------------------------------------
        # Group by New York calendar date.
        # ----------------------------------------------------

        data["_trading_date"] = data["timestamp"].dt.date

        grouped = data.groupby(
            "_trading_date",
            sort=True,
        )

        daily = grouped.agg(
            timestamp=("timestamp", "min"),
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            trade_count=("trade_count", "sum"),
        ).reset_index(drop=True)

        # ----------------------------------------------------
        # Calculate the volume-weighted average price for the
        # complete day's 30m bars.
        # ----------------------------------------------------

        vwap_values = []

        for _, group in grouped:

            volume = group["volume"].to_numpy(
                dtype=np.float64
            )

            vwap = group["vwap"].to_numpy(
                dtype=np.float64
            )

            volume_total = np.sum(volume)

            if volume_total > 0:
                daily_vwap = np.sum(
                    vwap * volume
                ) / volume_total
            else:
                daily_vwap = np.nan

            vwap_values.append(daily_vwap)

        daily["vwap"] = vwap_values

        day_data[symbol] = daily

    return day_data


LOADED_DAY_DATA = build_day_data_from_30m(
    LOADED_30M_DATA
)


# ============================================================
# END 2.6
# ============================================================








# ============================================================
# 2.7 VALIDATE DATA
# ============================================================

REQUIRED_MARKET_DATA_COLUMNS = (
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "trade_count",
    "vwap",
)


def validate_market_dataframe(
    symbol: str,
    timeframe: str,
    data: pd.DataFrame,
) -> list[str]:
    """
    Validate one stock/timeframe DataFrame.

    This function reports problems but does not modify the
    supplied DataFrame.
    """

    errors: list[str] = []

    # --------------------------------------------------------
    # Empty data
    # --------------------------------------------------------

    if data.empty:
        errors.append(
            f"{symbol} {timeframe}: data is empty."
        )
        return errors

    # --------------------------------------------------------
    # Required columns
    # --------------------------------------------------------

    missing_columns = [
        column
        for column in REQUIRED_MARKET_DATA_COLUMNS
        if column not in data.columns
    ]

    if missing_columns:
        errors.append(
            f"{symbol} {timeframe}: missing columns "
            f"{missing_columns}."
        )
        return errors

    # --------------------------------------------------------
    # Timestamp validation
    # --------------------------------------------------------

    timestamps = pd.to_datetime(
        data["timestamp"],
        errors="coerce",
    )

    invalid_timestamps = timestamps.isna().sum()

    if invalid_timestamps > 0:
        errors.append(
            f"{symbol} {timeframe}: "
            f"{invalid_timestamps} invalid timestamps."
        )

    # --------------------------------------------------------
    # OHLC numeric validation
    # --------------------------------------------------------

    ohlc_columns = (
        "open",
        "high",
        "low",
        "close",
    )

    for column in ohlc_columns:

        values = pd.to_numeric(
            data[column],
            errors="coerce",
        )

        invalid_values = values.isna().sum()

        if invalid_values > 0:
            errors.append(
                f"{symbol} {timeframe}: "
                f"{invalid_values} invalid {column} values."
            )

    # --------------------------------------------------------
    # OHLC logical validation
    # --------------------------------------------------------

    numeric_ohlc = data[
        list(ohlc_columns)
    ].apply(
        pd.to_numeric,
        errors="coerce",
    )

    valid_ohlc = numeric_ohlc.notna().all(axis=1)

    if valid_ohlc.any():

        valid_rows = numeric_ohlc.loc[
            valid_ohlc
        ]

        invalid_high = (
            valid_rows["high"]
            < valid_rows[
                ["open", "close", "low"]
            ].max(axis=1)
        )

        invalid_low = (
            valid_rows["low"]
            > valid_rows[
                ["open", "close", "high"]
            ].min(axis=1)
        )

        invalid_ohlc_count = int(
            (invalid_high | invalid_low).sum()
        )

        if invalid_ohlc_count > 0:
            errors.append(
                f"{symbol} {timeframe}: "
                f"{invalid_ohlc_count} invalid OHLC rows."
            )

    # --------------------------------------------------------
    # Non-positive prices
    # --------------------------------------------------------

    positive_price_check = (
        numeric_ohlc[
            ["open", "high", "low", "close"]
        ] <= 0
    )

    invalid_price_count = int(
        positive_price_check.any(axis=1).sum()
    )

    if invalid_price_count > 0:
        errors.append(
            f"{symbol} {timeframe}: "
            f"{invalid_price_count} rows contain "
            f"non-positive prices."
        )

    # --------------------------------------------------------
    # Duplicate bars
    # --------------------------------------------------------

    duplicate_timestamps = data[
        "timestamp"
    ].duplicated(
        keep=False
    )

    duplicate_count = int(
        duplicate_timestamps.sum()
    )

    if duplicate_count > 0:
        errors.append(
            f"{symbol} {timeframe}: "
            f"{duplicate_count} rows contain duplicate "
            f"timestamps."
        )

    # --------------------------------------------------------
    # Ordering
    # --------------------------------------------------------

    valid_timestamps = timestamps.dropna()

    if not valid_timestamps.is_monotonic_increasing:
        errors.append(
            f"{symbol} {timeframe}: timestamps are not "
            f"in chronological order."
        )

    return errors


def validate_all_market_data(
    data_5m: dict[str, pd.DataFrame],
    data_30m: dict[str, pd.DataFrame],
    data_day: dict[str, pd.DataFrame],
) -> dict[str, list[str]]:
    """
    Validate all loaded market data.

    Returns
    -------
    dict[str, list[str]]
        Validation errors grouped by stock.

    Example:

        {
            "AAPL": [
                "AAPL 5m: timestamps are not ..."
            ],
            "MU": []
        }

    Validation does not modify the data.
    """

    validation_errors: dict[str, list[str]] = {}

    for symbol in STOCK_SYMBOLS:

        errors: list[str] = []

        errors.extend(
            validate_market_dataframe(
                symbol,
                "5m",
                data_5m.get(
                    symbol,
                    pd.DataFrame(),
                ),
            )
        )

        errors.extend(
            validate_market_dataframe(
                symbol,
                "30m",
                data_30m.get(
                    symbol,
                    pd.DataFrame(),
                ),
            )
        )

        errors.extend(
            validate_market_dataframe(
                symbol,
                "day",
                data_day.get(
                    symbol,
                    pd.DataFrame(),
                ),
            )
        )

        validation_errors[symbol] = errors

    return validation_errors


MARKET_DATA_VALIDATION_ERRORS = (
    validate_all_market_data(
        LOADED_5M_DATA,
        LOADED_30M_DATA,
        LOADED_DAY_DATA,
    )
)


def raise_market_data_validation_errors(
    validation_errors: dict[str, list[str]],
) -> None:
    """
    Stop the process if invalid market data was found.

    This does not attempt to repair the data.
    """

    errors = [
        error
        for stock_errors in validation_errors.values()
        for error in stock_errors
    ]

    if errors:
        message = "\n".join(
            f"- {error}"
            for error in errors
        )

        raise ValueError(
            "Market data validation failed:\n"
            f"{message}"
        )


raise_market_data_validation_errors(
    MARKET_DATA_VALIDATION_ERRORS
)


# ============================================================
# END 2.7
# ============================================================







# ============================================================
# 2.8 ORGANIZE DATA BY STOCK AND TIMEFRAME
# ============================================================

def organize_market_data(
    data_5m: dict[str, pd.DataFrame],
    data_30m: dict[str, pd.DataFrame],
    data_day: dict[str, pd.DataFrame],
) -> dict[str, dict[str, pd.DataFrame]]:
    """
    Organize market data by stock and timeframe.

    Structure:

        {
            "AAPL": {
                "5m":   DataFrame,
                "30m":  DataFrame,
                "day":  DataFrame,
            },
            "MU": {
                "5m":   DataFrame,
                "30m":  DataFrame,
                "day":  DataFrame,
            }
        }

    The existing DataFrames are referenced directly.

    No copies are created for individual methods.
    """

    organized_data: dict[
        str,
        dict[str, pd.DataFrame]
    ] = {}

    for symbol in STOCK_SYMBOLS:

        organized_data[symbol] = {
            "5m": data_5m.get(
                symbol,
                pd.DataFrame(),
            ),
            "30m": data_30m.get(
                symbol,
                pd.DataFrame(),
            ),
            "day": data_day.get(
                symbol,
                pd.DataFrame(),
            ),
        }

    return organized_data


MARKET_DATA = organize_market_data(
    LOADED_5M_DATA,
    LOADED_30M_DATA,
    LOADED_DAY_DATA,
)


# ============================================================
# END 2.8
# ============================================================









# ============================================================
# 2.9 PASS DATA TO MARKET DATA STATE
# ============================================================

def pass_market_data_to_stock_states(
    market_data: dict[str, dict[str, pd.DataFrame]],
) -> None:
    """
    Put the shared market data into each StockState.

    Each StockState receives:

        market_data["5m"]
        market_data["30m"]
        market_data["day"]

    The existing DataFrames are referenced directly.

    No method-specific copies are created.
    """

    for symbol in STOCK_SYMBOLS:

        stock_state = STOCK_STATES[symbol]

        stock_state.market_data = market_data[symbol]


pass_market_data_to_stock_states(
    MARKET_DATA
)


# ============================================================
# END 2.9
# ============================================================





































# ============================================================
# 3. Prepare Market Data
# ============================================================


# ============================================================
# 3.1 Normalize Timestamps to New York Time
# ============================================================

def normalize_timestamp_column(data: pd.DataFrame) -> pd.DataFrame:
    """
    Convert the timestamp column to timezone-aware
    America/New_York timestamps.

    Returns a new DataFrame with normalized timestamps.
    """

    if data.empty:
        return data.copy()

    result = data.copy()

    timestamps = pd.to_datetime(result["timestamp"], utc=True)
    result["timestamp"] = timestamps.dt.tz_convert(TIMEZONE)

    return result


def normalize_market_data_timestamps(
    market_data: dict[str, dict[str, pd.DataFrame]]
) -> dict[str, dict[str, pd.DataFrame]]:
    """
    Normalize timestamps for every stock and timeframe.

    Structure:
        stock
            ├── 5m
            ├── 30m
            └── day
    """

    normalized_data = {}

    for symbol, timeframes in market_data.items():
        normalized_data[symbol] = {}

        for timeframe, data in timeframes.items():
            normalized_data[symbol][timeframe] = (
                normalize_timestamp_column(data)
            )

    return normalized_data


MARKET_DATA = normalize_market_data_timestamps(MARKET_DATA)


# Update the existing StockState references.
for symbol in STOCK_SYMBOLS:
    STOCK_STATES[symbol].market_data = MARKET_DATA[symbol]


# ============================================================
# End: 3.1 Normalize Timestamps to New York Time
# ============================================================









# ============================================================
# 3.2 Sort Data Chronologically
# ============================================================

def sort_market_data(data: pd.DataFrame) -> pd.DataFrame:
    """
    Sort market data from oldest to newest by timestamp.
    """

    if data.empty:
        return data.copy()

    result = data.sort_values(
        "timestamp",
        ascending=True
    ).reset_index(drop=True)

    return result


def sort_all_market_data(
    market_data: dict[str, dict[str, pd.DataFrame]]
) -> dict[str, dict[str, pd.DataFrame]]:
    """
    Sort every stock/timeframe chronologically.
    """

    sorted_data = {}

    for symbol, timeframes in market_data.items():
        sorted_data[symbol] = {}

        for timeframe, data in timeframes.items():
            sorted_data[symbol][timeframe] = sort_market_data(data)

    return sorted_data


MARKET_DATA = sort_all_market_data(MARKET_DATA)


# Update the existing StockState references.
for symbol in STOCK_SYMBOLS:
    STOCK_STATES[symbol].market_data = MARKET_DATA[symbol]


# ============================================================
# End: 3.2 Sort Data Chronologically
# ============================================================










# ============================================================
# 3.3 Handle Missing/Invalid Bars
# ============================================================

def clean_market_data(data: pd.DataFrame) -> pd.DataFrame:
    """
    Remove invalid market-data rows.

    Does not create or repair missing bars.
    Legitimate market gaps are preserved.
    """

    if data.empty:
        return data.copy()

    result = data.copy()

    # Remove rows with invalid timestamps.
    result = result.dropna(subset=["timestamp"])

    # Remove rows with missing OHLC values.
    result = result.dropna(
        subset=["open", "high", "low", "close"]
    )

    # Prices must be positive.
    valid_prices = (
        (result["open"] > 0)
        & (result["high"] > 0)
        & (result["low"] > 0)
        & (result["close"] > 0)
    )

    result = result.loc[valid_prices]

    # OHLC relationship must be valid.
    valid_ohlc = (
        (result["high"] >= result["open"])
        & (result["high"] >= result["close"])
        & (result["high"] >= result["low"])
        & (result["low"] <= result["open"])
        & (result["low"] <= result["close"])
    )

    result = result.loc[valid_ohlc]

    # Remove duplicate timestamps.
    result = result.drop_duplicates(
        subset=["timestamp"],
        keep="last"
    )

    return result.reset_index(drop=True)


def clean_all_market_data(
    market_data: dict[str, dict[str, pd.DataFrame]]
) -> dict[str, dict[str, pd.DataFrame]]:
    """
    Clean every stock/timeframe.
    """

    cleaned_data = {}

    for symbol, timeframes in market_data.items():
        cleaned_data[symbol] = {}

        for timeframe, data in timeframes.items():
            cleaned_data[symbol][timeframe] = clean_market_data(data)

    return cleaned_data


MARKET_DATA = clean_all_market_data(MARKET_DATA)


# Update the existing StockState references.
for symbol in STOCK_SYMBOLS:
    STOCK_STATES[symbol].market_data = MARKET_DATA[symbol]


# ============================================================
# End: 3.3 Handle Missing/Invalid Bars
# ============================================================









# ============================================================
# 3.4 Set Up 5m Data
# ============================================================

def prepare_5m_data(
    market_data: dict[str, dict[str, pd.DataFrame]]
) -> dict[str, dict[str, pd.DataFrame]]:
    """
    Prepare the shared 5-minute data for each stock.

    The 5m series contains:
        - premarket
        - regular market
        - after-hours

    No indicator calculations are performed here.
    No method-specific copies are created.
    """

    for symbol in STOCK_SYMBOLS:
        data = market_data[symbol]["5m"]

        # The 5m data has already been:
        #   1. timestamp-normalized
        #   2. sorted
        #   3. cleaned
        #
        # Keep the existing DataFrame as the shared
        # 5m market-data series.

        market_data[symbol]["5m"] = data

    return market_data


MARKET_DATA = prepare_5m_data(MARKET_DATA)


# Update the existing StockState references.
for symbol in STOCK_SYMBOLS:
    STOCK_STATES[symbol].market_data = MARKET_DATA[symbol]


# ============================================================
# End: 3.4 Set Up 5m Data
# ============================================================









# ============================================================
# 3.5 Set Up 30m Data
# ============================================================

def prepare_30m_data(
    market_data: dict[str, dict[str, pd.DataFrame]]
) -> dict[str, dict[str, pd.DataFrame]]:
    """
    Prepare the shared 30-minute data for each stock.

    The 30m series contains:
        - premarket
        - regular market
        - after-hours

    No indicator calculations are performed here.
    No method-specific copies are created.
    """

    for symbol in STOCK_SYMBOLS:
        data = market_data[symbol]["30m"]

        # The 30m data has already been:
        #   1. timestamp-normalized
        #   2. sorted
        #   3. cleaned
        #
        # Keep the existing DataFrame as the shared
        # 30m market-data series.

        market_data[symbol]["30m"] = data

    return market_data


MARKET_DATA = prepare_30m_data(MARKET_DATA)


# Update the existing StockState references.
for symbol in STOCK_SYMBOLS:
    STOCK_STATES[symbol].market_data = MARKET_DATA[symbol]


# ============================================================
# End: 3.5 Set Up 30m Data
# ============================================================








# ============================================================
# 3.6 Set Up Day Data
# ============================================================

def prepare_day_data(
    market_data: dict[str, dict[str, pd.DataFrame]]
) -> dict[str, dict[str, pd.DataFrame]]:
    """
    Prepare the shared daily data for each stock.

    Daily data was already built from the 30m extended-hours
    data during Section 2.

    This step only verifies that the existing daily series
    is present and keeps it as the shared day DataFrame.

    No new daily data is downloaded.
    No daily bars are rebuilt here.
    No indicator calculations are performed.
    """

    for symbol in STOCK_SYMBOLS:
        day_data = market_data[symbol]["day"]

        if day_data is None:
            raise ValueError(
                f"Missing day data for {symbol}."
            )

        if not isinstance(day_data, pd.DataFrame):
            raise TypeError(
                f"Day data for {symbol} must be a pandas DataFrame."
            )

        market_data[symbol]["day"] = day_data

    return market_data


MARKET_DATA = prepare_day_data(MARKET_DATA)


# Update the existing StockState references.
for symbol in STOCK_SYMBOLS:
    STOCK_STATES[symbol].market_data = MARKET_DATA[symbol]


# ============================================================
# End: 3.6 Set Up Day Data
# ============================================================






# ============================================================
# 3.7 Align Timeframes
# ============================================================

def validate_timeframe_timestamps(
    data: pd.DataFrame,
    timeframe: str
) -> None:
    """
    Verify that timestamps are timezone-aware and use
    America/New_York.

    This does not force different timeframes to have
    identical timestamps.
    """

    if data.empty:
        return

    timestamps = data["timestamp"]

    if timestamps.dt.tz is None:
        raise ValueError(
            f"{timeframe} timestamps are not timezone-aware."
        )

    if str(timestamps.dt.tz) != str(TIMEZONE):
        raise ValueError(
            f"{timeframe} timestamps are not in "
            f"{TIMEZONE}."
        )


def align_market_data_timeframes(
    market_data: dict[str, dict[str, pd.DataFrame]]
) -> dict[str, dict[str, pd.DataFrame]]:
    """
    Verify that each timeframe has a consistent timestamp
    representation.

    Timeframes remain independent:

        5m  -> individual 5-minute bars
        30m -> individual 30-minute bars
        day -> daily bars

    No timestamps are added, removed, or forced to match
    between timeframes.
    """

    for symbol in STOCK_SYMBOLS:
        for timeframe in TIMEFRAMES:
            data = market_data[symbol][timeframe]

            validate_timeframe_timestamps(
                data,
                timeframe
            )

    return market_data


MARKET_DATA = align_market_data_timeframes(MARKET_DATA)


# Update the existing StockState references.
for symbol in STOCK_SYMBOLS:
    STOCK_STATES[symbol].market_data = MARKET_DATA[symbol]


# ============================================================
# End: 3.7 Align Timeframes
# ============================================================







# ============================================================
# 3.8 Prepare Rolling-Window Data
# ============================================================

def get_required_indicator_history() -> int:
    """
    Return the largest historical window required by the
    indicator calculations.
    """

    return max(
        max(EMA_PERIODS),
        ROC_PERIOD + 1,
        CANDLE_AVERAGE_WINDOW
    )


REQUIRED_INDICATOR_HISTORY = get_required_indicator_history()


def prepare_rolling_window_data(
    data: pd.DataFrame,
    required_history: int
) -> pd.DataFrame:
    """
    Verify that the market data contains enough historical
    bars for indicator initialization.

    No rolling calculations are performed here.

    The complete ordered DataFrame is retained because the
    historical simulation will need the bars chronologically.
    """

    if data.empty:
        return data

    if len(data) < required_history:
        raise ValueError(
            f"Insufficient historical data for indicator "
            f"initialization. Required at least "
            f"{required_history} bars, found {len(data)}."
        )

    return data


def prepare_all_rolling_window_data(
    market_data: dict[str, dict[str, pd.DataFrame]]
) -> dict[str, dict[str, pd.DataFrame]]:
    """
    Prepare historical data for all stocks and timeframes.
    """

    for symbol in STOCK_SYMBOLS:
        for timeframe in TIMEFRAMES:
            market_data[symbol][timeframe] = (
                prepare_rolling_window_data(
                    market_data[symbol][timeframe],
                    REQUIRED_INDICATOR_HISTORY
                )
            )

    return market_data


MARKET_DATA = prepare_all_rolling_window_data(MARKET_DATA)


# Update the existing StockState references.
for symbol in STOCK_SYMBOLS:
    STOCK_STATES[symbol].market_data = MARKET_DATA[symbol]


# ============================================================
# End: 3.8 Prepare Rolling-Window Data
# ============================================================






# ============================================================
# 3.9 Prepare Data for Indicator Initialization
# ============================================================

def prepare_indicator_input(data: pd.DataFrame) -> dict:
    """
    Prepare the ordered OHLC and timestamp arrays that will be
    given to the indicator initialization stage.

    The original DataFrame remains the shared market-data
    source.

    No indicators are calculated here.
    """

    if data.empty:
        return {
            "timestamps": np.empty(0, dtype=object),
            "open": np.empty(0, dtype=np.float64),
            "high": np.empty(0, dtype=np.float64),
            "low": np.empty(0, dtype=np.float64),
            "close": np.empty(0, dtype=np.float64),
        }

    return {
        "timestamps": data["timestamp"].to_numpy(copy=False),
        "open": data["open"].to_numpy(dtype=np.float64, copy=False),
        "high": data["high"].to_numpy(dtype=np.float64, copy=False),
        "low": data["low"].to_numpy(dtype=np.float64, copy=False),
        "close": data["close"].to_numpy(dtype=np.float64, copy=False),
    }


def prepare_all_indicator_inputs(
    market_data: dict[str, dict[str, pd.DataFrame]]
) -> dict[str, dict[str, dict]]:
    """
    Prepare indicator input data for every stock/timeframe.
    """

    indicator_inputs = {}

    for symbol in STOCK_SYMBOLS:
        indicator_inputs[symbol] = {}

        for timeframe in TIMEFRAMES:
            indicator_inputs[symbol][timeframe] = (
                prepare_indicator_input(
                    market_data[symbol][timeframe]
                )
            )

    return indicator_inputs


INDICATOR_INPUT_DATA = prepare_all_indicator_inputs(MARKET_DATA)


# ============================================================
# End: 3.9 Prepare Data for Indicator Initialization
# ============================================================








# ============================================================
# 3.10 Finalize Market Data State
# ============================================================

def finalize_market_data_state(
    market_data: dict[str, dict[str, pd.DataFrame]]
) -> None:
    """
    Store the prepared market data in each existing StockState.

    Final structure:

        STOCK_STATES[symbol].market_data
            ├── "5m"
            ├── "30m"
            └── "day"

    The DataFrames remain shared by all methods for that
    stock/timeframe.
    """

    for symbol in STOCK_SYMBOLS:
        if symbol not in market_data:
            raise KeyError(
                f"Market data missing for stock: {symbol}"
            )

        for timeframe in TIMEFRAMES:
            if timeframe not in market_data[symbol]:
                raise KeyError(
                    f"Missing {timeframe} market data "
                    f"for {symbol}."
                )

        STOCK_STATES[symbol].market_data = market_data[symbol]


finalize_market_data_state(MARKET_DATA)


# ============================================================
# End: 3.10 Finalize Market Data State
# ============================================================


# ============================================================
# End: 3. Prepare Market Data
# ============================================================