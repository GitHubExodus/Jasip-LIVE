# market_data.py

from datetime import datetime, timedelta

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame


# ============================================================
# ALPACA CONNECTION
# ============================================================

def create_data_client(api_key, secret_key):
    """
    Input:
        api_key: Alpaca API key
        secret_key: Alpaca secret key

    Description:
        Creates an Alpaca historical market-data client.

    Output:
        Alpaca StockHistoricalDataClient
    """

    return StockHistoricalDataClient(
        api_key,
        secret_key,
    )


# ============================================================
# HISTORICAL 5-MINUTE DATA
# ============================================================

def download_5m_data(
    client,
    symbol,
    start,
    end,
):
    """
    Input:
        client: Alpaca market-data client
        symbol: stock symbol
        start: starting datetime
        end: ending datetime

    Description:
        Downloads historical 5-minute stock bars.

    Output:
        pandas.DataFrame
    """

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame(5, "Min"),
        start=start,
        end=end,
    )

    bars = client.get_stock_bars(request)

    dataframe = bars.df.reset_index()

    return dataframe


# ============================================================
# UPDATE 5-MINUTE DATA
# ============================================================

def download_latest_5m_bar(
    client,
    symbol,
    start,
    end,
):
    """
    Input:
        client: Alpaca market-data client
        symbol: stock symbol
        start: beginning of requested range
        end: end of requested range

    Description:
        Downloads the newest available 5-minute bars.

    Output:
        pandas.DataFrame
    """

    return download_5m_data(
        client=client,
        symbol=symbol,
        start=start,
        end=end,
    )


# ============================================================
# APPEND NEW DATA
# ============================================================

def append_new_5m_data(
    existing_data,
    new_data,
):
    """
    Input:
        existing_data: existing 5-minute DataFrame
        new_data: newly downloaded 5-minute DataFrame

    Description:
        Appends new bars, removes duplicate timestamps,
        sorts chronologically, and returns the updated data.

    Output:
        pandas.DataFrame
    """

    if new_data.empty:
        return existing_data

    combined = pd.concat(
        [
            existing_data,
            new_data,
        ],
        ignore_index=True,
    )

    combined = combined.drop_duplicates(
        subset=["symbol", "timestamp"],
        keep="last",
    )

    combined = combined.sort_values(
        ["symbol", "timestamp"]
    ).reset_index(drop=True)

    return combined


# ============================================================
# CANDLE BOUNDARY
# ============================================================

def get_next_5m_boundary(current_time):
    """
    Input:
        current_time: datetime

    Description:
        Calculates the next 5-minute candle boundary.

    Output:
        datetime
    """

    next_minute = (
        (current_time.minute // 5) + 1
    ) * 5

    next_boundary = current_time.replace(
        minute=0,
        second=0,
        microsecond=0,
    ) + timedelta(minutes=next_minute)

    return next_boundary


# ============================================================
# NEXT CANDLE EVENT
# ============================================================

def get_next_candle_time(current_time):
    """
    Input:
        current_time: datetime

    Description:
        Determines when the next completed 5-minute candle
        becomes available, including the configured safety delay.

    Output:
        datetime
    """

    from old2.config import CANDLE_CONFIRMATION_DELAY_SECONDS

    boundary = get_next_5m_boundary(current_time)

    return boundary + timedelta(
        seconds=CANDLE_CONFIRMATION_DELAY_SECONDS
    )


# ============================================================
# CALCULATION BAR
# ============================================================

def get_calculation_bar(data):
    """
    Input:
        data: 5-minute market DataFrame

    Description:
        Returns the second-most-recent market bar.
        The newest market bar is intentionally excluded
        from indicator and strategy calculations.

    Output:
        pandas.Series
    """

    if len(data) < 2:
        return None

    return data.iloc[-2]


# ============================================================
# CALCULATION BAR TIMESTAMP
# ============================================================

def get_calculation_timestamp(data):
    """
    Input:
        data: market DataFrame

    Description:
        Gets the timestamp of the calculation bar.

    Output:
        datetime or None
    """

    bar = get_calculation_bar(data)

    if bar is None:
        return None

    return bar["timestamp"]