# ==========================================
# Script Name: data.py
# Purpose: Data fetching, ingestion, normalization, and bar aggregation
# Dependencies: config.py, alpaca, pandas
# ==========================================

import pandas as pd
from typing import Dict, List, Optional, Union
from datetime import datetime, timezone
from dataclasses import dataclass, field
import logging

import config

logger = logging.getLogger("DataSubsystem")

# Optional Alpaca SDK import guard
try:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    ALPACA_AVAILABLE = True
except ImportError:
    ALPACA_AVAILABLE = False


# ==========================================
# Start: 1.1 Data Configuration & Symbols
# ==========================================

STANDARD_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
SUPPORTED_TIMEFRAMES = ["5m", "30m", "1d"]


@dataclass
class DataManager:
    """
    Wrapper container holding multi-timeframe normalized DataFrames for a symbol.
    Provides standard interface methods used across simulation and live modules.
    """
    symbol: str
    timeframes: Dict[str, pd.DataFrame] = field(default_factory=dict)

    def get_timeframe(self, tf: str) -> pd.DataFrame:
        """Retrieves DataFrame for specified timeframe."""
        return self.timeframes.get(tf, pd.DataFrame(columns=STANDARD_COLUMNS))

    def set_timeframe(self, tf: str, df: pd.DataFrame) -> None:
        """Sets or updates DataFrame for specified timeframe."""
        self.timeframes[tf] = df

    def latest(self, tf: str) -> Optional[pd.Series]:
        """Returns the latest bar series for a specific timeframe."""
        df = self.get_timeframe(tf)
        if not df.empty:
            return df.iloc[-1]
        return None


def get_symbol_universe(cfg: Optional[dict] = None) -> List[str]:
    """Retrieves the master universe of stock symbols to process."""
    if cfg and "symbols" in cfg:
        return cfg["symbols"]
    if hasattr(config, "SYMBOLS"):
        return config.SYMBOLS
    return ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "PEP", "COST"]


def validate_timeframe(timeframe: str) -> bool:
    """Validates whether a given timeframe string is supported."""
    return timeframe in SUPPORTED_TIMEFRAMES

# ==========================================
# End: 1.1 Data Configuration & Symbols
# ==========================================


# ==========================================
# Start: 1.2 Alpaca Bar Data Ingestion
# ==========================================

def _get_alpaca_timeframe_unit(tf_str: str):
    """Maps internal string timeframe to Alpaca SDK TimeFrame object."""
    if not ALPACA_AVAILABLE:
        return None
    if tf_str == "5m":
        return TimeFrame(5, TimeFrameUnit.Minute)
    elif tf_str == "30m":
        return TimeFrame(30, TimeFrameUnit.Minute)
    elif tf_str == "1d":
        return TimeFrame(1, TimeFrameUnit.Day)
    raise ValueError(f"Unsupported timeframe for Alpaca mapping: {tf_str}")


def fetch_alpaca_bars(
    symbols: List[str],
    timeframe: str,
    start: datetime,
    end: Optional[datetime] = None,
    alpaca_client: Optional[object] = None
) -> Dict[str, pd.DataFrame]:
    """
    Fetches raw OHLCV market bars from Alpaca for a list of symbols.
    """
    if not validate_timeframe(timeframe):
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    raw_data: Dict[str, pd.DataFrame] = {sym: pd.DataFrame() for sym in symbols}

    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end is not None and end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    # 1. Execute via SDK Client instance if provided
    if alpaca_client is not None and ALPACA_AVAILABLE and isinstance(alpaca_client, StockHistoricalDataClient):
        try:
            alpaca_tf = _get_alpaca_timeframe_unit(timeframe)
            request_params = StockBarsRequest(
                symbol_or_symbols=symbols,
                timeframe=alpaca_tf,
                start=start,
                end=end
            )
            bars_response = alpaca_client.get_stock_bars(request_params)
            
            # Group response into per-symbol DataFrames
            if hasattr(bars_response, "df"):
                df_all = bars_response.df
                if not df_all.empty:
                    for sym in symbols:
                        if sym in df_all.index.levels[0]:
                            raw_data[sym] = df_all.xs(sym).reset_index()
            return raw_data
        except Exception as e:
            logger.error(f"Alpaca API error during bar fetching: {e}")

    # 2. Defensive Fallback / Empty Schema Generation
    for symbol in symbols:
        raw_data[symbol] = pd.DataFrame(columns=[
            "timestamp", "open", "high", "low", "close", "volume"
        ])

    return raw_data

# ==========================================
# End: 1.2 Alpaca Bar Data Ingestion
# ==========================================


# ==========================================
# Start: 1.3 Data Normalization
# ==========================================

def normalize_bar_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Standardizes a DataFrame of OHLCV bars into canonical system schema.
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    normalized = df.copy()

    # Column mapping dictionary
    rename_map = {
        "time": "timestamp",
        "t": "timestamp",
        "o": "open",
        "h": "high",
        "l": "low",
        "c": "close",
        "v": "volume",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
        "Timestamp": "timestamp"
    }
    normalized = normalized.rename(columns=rename_map)

    # Handle datetime conversion and timezone normalization
    if "timestamp" in normalized.columns:
        normalized["timestamp"] = pd.to_datetime(normalized["timestamp"], utc=True)
    elif isinstance(normalized.index, pd.DatetimeIndex):
        normalized = normalized.reset_index()
        normalized = normalized.rename(columns={"index": "timestamp"})
        normalized["timestamp"] = pd.to_datetime(normalized["timestamp"], utc=True)

    # Convert timestamps to target timezone (America/New_York)
    if "timestamp" in normalized.columns:
        tz_target = getattr(config, "TIMEZONE", timezone.utc)
        normalized["timestamp"] = normalized["timestamp"].dt.tz_convert(tz_target)

    # Validate numeric types
    numeric_cols = ["open", "high", "low", "close", "volume"]
    for col in numeric_cols:
        if col in normalized.columns:
            normalized[col] = pd.to_numeric(normalized[col], errors="coerce")

    # Drop duplicates & enforce chronological sorting
    normalized = normalized.drop_duplicates(subset=["timestamp"])
    normalized = normalized.sort_values(by="timestamp").reset_index(drop=True)

    # Enforce standard columns
    available_cols = [col for col in STANDARD_COLUMNS if col in normalized.columns]
    return normalized[available_cols]

# ==========================================
# End: 1.3 Data Normalization
# ==========================================


# ==========================================
# Start: 1.4 Daily Bar Building from 30m Bars
# ==========================================

def build_daily_from_30m(df_30m: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregates 30-minute bar data into standard 1-day OHLCV bars.
    """
    if df_30m.empty:
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    df = df_30m.copy()
    
    # Extract trading date
    df["date"] = df["timestamp"].dt.date

    # Group by trading date
    daily_groups = df.groupby("date")

    daily_bars = pd.DataFrame({
        "timestamp": daily_groups["timestamp"].last(),
        "open": daily_groups["open"].first(),
        "high": daily_groups["high"].max(),
        "low": daily_groups["low"].min(),
        "close": daily_groups["close"].last(),
        "volume": daily_groups["volume"].sum()
    }).reset_index(drop=True)

    return normalize_bar_data(daily_bars)

# ==========================================
# End: 1.4 Daily Bar Building from 30m Bars
# ==========================================


# ==========================================
# Start: 1.5 Incremental Bar Update Mechanics
# ==========================================

def update_bar_series(existing_df: pd.DataFrame, new_bar: Union[dict, pd.Series, pd.DataFrame]) -> pd.DataFrame:
    """
    Updates an existing bar dataset with a new bar incrementally.
    Overwrites the latest bar if timestamps match or appends if newer.
    """
    if isinstance(new_bar, dict):
        new_df = pd.DataFrame([new_bar])
    elif isinstance(new_bar, pd.Series):
        new_df = pd.DataFrame([new_bar])
    else:
        new_df = new_bar.copy()

    new_df = normalize_bar_data(new_df)

    if existing_df.empty:
        return new_df

    if new_df.empty:
        return existing_df

    updated_df = existing_df.copy()
    
    latest_existing_ts = updated_df["timestamp"].iloc[-1]
    new_ts = new_df["timestamp"].iloc[0]

    if new_ts == latest_existing_ts:
        # Overwrite in-progress bar
        updated_df.iloc[-1] = new_df.iloc[0]
    elif new_ts > latest_existing_ts:
        # Append completed bar
        updated_df = pd.concat([updated_df, new_df], ignore_index=True)

    return updated_df

# ==========================================
# End: 1.5 Incremental Bar Update Mechanics
# ==========================================


# ==========================================
# Start: 1.6 Data Interface & Stock Initializer
# ==========================================

def get_historical_data(
    symbols: List[str],
    timeframe: str,
    start: datetime,
    end: Optional[datetime] = None,
    alpaca_client: Optional[object] = None
) -> Dict[str, pd.DataFrame]:
    """
    Public API: Fetches and normalizes historical market data for given symbols and timeframe.
    """
    if timeframe == "1d":
        raw_30m = fetch_alpaca_bars(symbols, "30m", start, end, alpaca_client)
        result = {}
        for symbol, df in raw_30m.items():
            norm_30m = normalize_bar_data(df)
            result[symbol] = build_daily_from_30m(norm_30m)
        return result

    raw_bars = fetch_alpaca_bars(symbols, timeframe, start, end, alpaca_client)
    return {symbol: normalize_bar_data(df) for symbol, df in raw_bars.items()}


def initialize_stock(
    symbol: str,
    start_time: Optional[datetime] = None,
    alpaca_client: Optional[object] = None
) -> DataManager:
    """
    Helper required by morning.py and live.py to initialize all supported 
    timeframes (5m, 30m, 1d) into a DataManager for a single stock symbol.
    """
    if start_time is None:
        # Default lookback of 60 calendar days if no timestamp is provided
        start_time = datetime.now(timezone.utc) - pd.Timedelta(days=60)

    manager = DataManager(symbol=symbol)

    # Fetch 5m and 30m intraday series
    bars_5m = get_historical_data([symbol], "5m", start_time, alpaca_client=alpaca_client)
    bars_30m = get_historical_data([symbol], "30m", start_time, alpaca_client=alpaca_client)

    df_5m = bars_5m.get(symbol, pd.DataFrame(columns=STANDARD_COLUMNS))
    df_30m = bars_30m.get(symbol, pd.DataFrame(columns=STANDARD_COLUMNS))
    df_1d = build_daily_from_30m(df_30m)

    manager.set_timeframe("5m", df_5m)
    manager.set_timeframe("30m", df_30m)
    manager.set_timeframe("1d", df_1d)

    return manager


def update_market_data(
    current_data: Dict[str, pd.DataFrame],
    new_bars: Dict[str, Union[dict, pd.Series, pd.DataFrame]],
    timeframe: str
) -> Dict[str, pd.DataFrame]:
    """
    Public API: Incrementally updates current market data structures with incoming bar updates.
    """
    updated_dataset: Dict[str, pd.DataFrame] = {}

    for symbol, df in current_data.items():
        if symbol in new_bars:
            updated_df = update_bar_series(df, new_bars[symbol])
            updated_dataset[symbol] = updated_df
        else:
            updated_dataset[symbol] = df

    return updated_dataset

# ==========================================
# End: 1.6 Data Interface & Stock Initializer
# ==========================================