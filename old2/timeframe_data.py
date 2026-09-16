# timeframe_data.py

import pandas as pd

from old2.config import MARKET_TIMEZONE


# ============================================================
# 30-MINUTE DATA
# ============================================================

def build_30m_data(data_5m):
    """
    Input:
        data_5m: 5-minute market DataFrame

    Description:
        Builds 30-minute candles from 5-minute candles.
        Includes premarket, regular hours, and after-hours.

    Output:
        30-minute DataFrame
    """

    if data_5m.empty:
        return pd.DataFrame(
            columns=data_5m.columns
        )

    data = data_5m.copy()

    data["timestamp"] = pd.to_datetime(
        data["timestamp"],
        utc=True,
    ).dt.tz_convert(MARKET_TIMEZONE)

    data = data.sort_values("timestamp")

    data = data.set_index("timestamp")

    result = data.resample(
        "30min",
        label="left",
        closed="left",
    ).agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "vol": "sum",
            "trade_count": "sum",
            "vwap": "last",
        }
    )

    result = result.dropna(
        subset=["open", "high", "low", "close"]
    )

    result = result.reset_index()

    return result


# ============================================================
# DAY DATA
# ============================================================

def build_day_data(data_30m):
    """
    Input:
        data_30m: 30-minute market DataFrame

    Description:
        Builds daily candles from 30-minute candles.

    Output:
        Daily DataFrame
    """

    if data_30m.empty:
        return pd.DataFrame(
            columns=data_30m.columns
        )

    data = data_30m.copy()

    data["timestamp"] = pd.to_datetime(
        data["timestamp"],
        utc=True,
    ).dt.tz_convert(MARKET_TIMEZONE)

    data = data.sort_values("timestamp")

    data = data.set_index("timestamp")

    result = data.resample(
        "1D"
    ).agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "vol": "sum",
            "trade_count": "sum",
            "vwap": "last",
        }
    )

    result = result.dropna(
        subset=["open", "high", "low", "close"]
    )

    result = result.reset_index()

    return result


# ============================================================
# WEEK DATA
# ============================================================

def build_week_data(data_day):
    """
    Input:
        data_day: daily market DataFrame

    Description:
        Builds weekly candles from daily candles.

    Output:
        Weekly DataFrame
    """

    if data_day.empty:
        return pd.DataFrame(
            columns=data_day.columns
        )

    data = data_day.copy()

    data["timestamp"] = pd.to_datetime(
        data["timestamp"],
        utc=True,
    ).dt.tz_convert(MARKET_TIMEZONE)

    data = data.sort_values("timestamp")

    data = data.set_index("timestamp")

    result = data.resample(
        "W-MON",
        label="left",
        closed="left",
    ).agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "vol": "sum",
            "trade_count": "sum",
            "vwap": "last",
        }
    )

    result = result.dropna(
        subset=["open", "high", "low", "close"]
    )

    result = result.reset_index()

    return result


# ============================================================
# BUILD ALL TIMEFRAMES
# ============================================================

def build_all_timeframes(data_5m):
    """
    Input:
        data_5m: 5-minute market DataFrame

    Description:
        Builds the complete timeframe hierarchy:
        5m → 30m → day → week.

    Output:
        dictionary containing 5m, 30m, day, and week DataFrames
    """

    data_30m = build_30m_data(data_5m)

    data_day = build_day_data(data_30m)

    data_week = build_week_data(data_day)

    return {
        "5m": data_5m,
        "30m": data_30m,
        "day": data_day,
        "week": data_week,
    }


# ============================================================
# INCREMENTAL 30-MINUTE UPDATE
# ============================================================

def update_30m_data(
    existing_30m,
    data_5m,
):
    """
    Input:
        existing_30m: existing 30-minute DataFrame
        data_5m: latest 5-minute data

    Description:
        Updates the 30-minute timeframe using the latest
        available 5-minute data.

    Output:
        Updated 30-minute DataFrame
    """

    if data_5m.empty:
        return existing_30m

    latest_timestamp = pd.to_datetime(
        data_5m["timestamp"]
    ).max()

    if existing_30m.empty:
        return build_30m_data(data_5m)

    existing = existing_30m.copy()

    existing["timestamp"] = pd.to_datetime(
        existing["timestamp"]
    )

    # Only rebuild the current 30-minute period and anything newer.
    current_period = latest_timestamp.floor("30min")

    historical = existing[
        existing["timestamp"] < current_period
    ].copy()

    recent_5m = data_5m[
        pd.to_datetime(data_5m["timestamp"]) >= current_period
    ].copy()

    recent_30m = build_30m_data(recent_5m)

    result = pd.concat(
        [
            historical,
            recent_30m,
        ],
        ignore_index=True,
    )

    result = result.drop_duplicates(
        subset=["timestamp"],
        keep="last",
    )

    result = result.sort_values(
        "timestamp"
    ).reset_index(drop=True)

    return result


# ============================================================
# INCREMENTAL DAY UPDATE
# ============================================================

def update_day_data(
    existing_day,
    data_30m,
):
    """
    Input:
        existing_day: existing daily DataFrame
        data_30m: latest 30-minute data

    Description:
        Updates only the current daily period and newer data.

    Output:
        Updated daily DataFrame
    """

    if data_30m.empty:
        return existing_day

    if existing_day.empty:
        return build_day_data(data_30m)

    latest_timestamp = pd.to_datetime(
        data_30m["timestamp"]
    ).max()

    current_day = latest_timestamp.normalize()

    existing = existing_day.copy()

    existing["timestamp"] = pd.to_datetime(
        existing["timestamp"]
    )

    historical = existing[
        existing["timestamp"] < current_day
    ].copy()

    recent_30m = data_30m[
        pd.to_datetime(data_30m["timestamp"]) >= current_day
    ].copy()

    recent_day = build_day_data(recent_30m)

    result = pd.concat(
        [
            historical,
            recent_day,
        ],
        ignore_index=True,
    )

    result = result.drop_duplicates(
        subset=["timestamp"],
        keep="last",
    )

    result = result.sort_values(
        "timestamp"
    ).reset_index(drop=True)

    return result


# ============================================================
# INCREMENTAL WEEK UPDATE
# ============================================================

def update_week_data(
    existing_week,
    data_day,
):
    """
    Input:
        existing_week: existing weekly DataFrame
        data_day: latest daily data

    Description:
        Updates only the current weekly period and newer data.

    Output:
        Updated weekly DataFrame
    """

    if data_day.empty:
        return existing_week

    if existing_week.empty:
        return build_week_data(data_day)

    latest_timestamp = pd.to_datetime(
        data_day["timestamp"]
    ).max()

    current_week = (
        latest_timestamp
        - pd.to_timedelta(
            latest_timestamp.weekday(),
            unit="D",
        )
    ).normalize()

    existing = existing_week.copy()

    existing["timestamp"] = pd.to_datetime(
        existing["timestamp"]
    )

    historical = existing[
        existing["timestamp"] < current_week
    ].copy()

    recent_day = data_day[
        pd.to_datetime(data_day["timestamp"]) >= current_week
    ].copy()

    recent_week = build_week_data(recent_day)

    result = pd.concat(
        [
            historical,
            recent_week,
        ],
        ignore_index=True,
    )

    result = result.drop_duplicates(
        subset=["timestamp"],
        keep="last",
    )

    result = result.sort_values(
        "timestamp"
    ).reset_index(drop=True)

    return result


# ============================================================
# INCREMENTAL UPDATE OF ALL TIMEFRAMES
# ============================================================

def update_all_timeframes(
    data_5m,
    existing_30m,
    existing_day,
    existing_week,
):
    """
    Input:
        data_5m: updated 5-minute DataFrame
        existing_30m: existing 30-minute DataFrame
        existing_day: existing daily DataFrame
        existing_week: existing weekly DataFrame

    Description:
        Incrementally updates the complete timeframe hierarchy:
        5m → 30m → day → week.

    Output:
        dictionary containing updated 5m, 30m, day, and week data
    """

    data_30m = update_30m_data(
        existing_30m,
        data_5m,
    )

    data_day = update_day_data(
        existing_day,
        data_30m,
    )

    data_week = update_week_data(
        existing_week,
        data_day,
    )

    return {
        "5m": data_5m,
        "30m": data_30m,
        "day": data_day,
        "week": data_week,
    }