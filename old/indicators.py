import numpy as np
import pandas as pd

from numba import njit

from old.config import (
    EMA_PAIRS,
    NEW_YORK_TIMEZONE,
)


# ============================================================
# EMA
# ============================================================

@njit(cache=True)
def ema_numba(
    values,
    period,
):
    """
    Calculate EMA using NumPy/Numba.

    NaN values are preserved until enough valid
    observations exist.
    """

    n = len(values)

    result = np.full(
        n,
        np.nan,
        dtype=np.float64,
    )

    if n == 0:
        return result

    alpha = (
        2.0
        /
        (period + 1.0)
    )

    first_index = -1

    for i in range(n):

        if np.isfinite(values[i]):

            first_index = i
            break

    if first_index == -1:
        return result

    result[first_index] = (
        values[first_index]
    )

    for i in range(
        first_index + 1,
        n,
    ):

        value = values[i]

        if np.isfinite(value):

            result[i] = (
                alpha * value
                +
                (1.0 - alpha)
                * result[i - 1]
            )

        else:

            result[i] = (
                result[i - 1]
            )

    return result


# ============================================================
# PREPARE DATA
# ============================================================

def prepare_data(data):
    """
    Normalize Alpaca data.

    Timestamp is always converted to UTC first,
    then used as the canonical timezone-aware index.
    """

    if data is None:
        return pd.DataFrame()

    if len(data) == 0:
        return pd.DataFrame()

    df = data.copy()

    if "timestamp" in df.columns:

        df["timestamp"] = (
            pd.to_datetime(
                df["timestamp"],
                utc=True,
            )
        )

    elif df.index.name == "timestamp":

        df.index = (
            pd.to_datetime(
                df.index,
                utc=True,
            )
        )

    else:

        raise ValueError(
            "Data must contain timestamp."
        )

    df = (
        df
        .sort_values("timestamp")
        .drop_duplicates(
            subset=["timestamp"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    numeric_columns = (
        "open",
        "high",
        "low",
        "close",
        "volume",
        "trade_count",
        "vwap",
    )

    for column in numeric_columns:

        if column in df.columns:

            df[column] = pd.to_numeric(
                df[column],
                errors="coerce",
            )

    return df


# ============================================================
# ADD EMAS
# ============================================================

def add_emas(
    data,
    periods=None,
):
    """
    Add all required EMAs.

    EMA columns:

        ema_3
        ema_5
        ...
    """

    if periods is None:

        periods = sorted(
            set(
                period
                for pair in EMA_PAIRS
                for period in pair
            )
        )

    df = data.copy()

    close_values = np.asarray(
        df["close"],
        dtype=np.float64,
    )

    for period in periods:

        df[
            f"ema_{period}"
        ] = ema_numba(
            close_values,
            period,
        )

    return df


# ============================================================
# TIMEFRAME RULE
# ============================================================

def timeframe_rule(
    timeframe,
):
    rules = {

        "1m": "1min",

        "5m": "5min",

        "30m": "30min",

        "1h": "1h",

        "1d": "1D",

        "1w": "1W-MON",
    }

    if timeframe not in rules:

        raise ValueError(
            f"Unsupported timeframe: {timeframe}"
        )

    return rules[timeframe]


# ============================================================
# RESAMPLE
# ============================================================

def resample_timeframe(
    minute_or_lower_data,
    timeframe,
):
    """
    This function is intentionally NOT used for startup
    historical data.

    It is retained for situations where a lower-timeframe
    stream needs to be transformed locally.

    Historical startup data comes directly from Alpaca
    at the requested timeframe.
    """

    if timeframe == "1m":

        return minute_or_lower_data.copy()

    df = minute_or_lower_data.copy()

    if len(df) == 0:

        return df

    df["timestamp"] = (
        pd.to_datetime(
            df["timestamp"],
            utc=True,
        )
    )

    df = (
        df
        .set_index("timestamp")
        .sort_index()
    )

    ny = (
        df.index
        .tz_convert(
            NEW_YORK_TIMEZONE
        )
    )

    df.index = ny

    aggregation = {

        "open": "first",

        "high": "max",

        "low": "min",

        "close": "last",

        "volume": "sum",
    }

    if "trade_count" in df.columns:

        aggregation[
            "trade_count"
        ] = "sum"

    if "vwap" in df.columns:

        aggregation[
            "vwap"
        ] = "mean"

    result = (
        df
        .resample(
            timeframe_rule(
                timeframe
            ),
            label="right",
            closed="right",
        )
        .agg(aggregation)
        .dropna(
            subset=["open", "high", "low", "close"]
        )
        .reset_index()
    )

    result["timestamp"] = (
        result["timestamp"]
        .dt.tz_convert("UTC")
    )

    return result


# ============================================================
# GET CURRENT TIMEFRAME BUCKET
# ============================================================

def get_timeframe_bucket(
    timestamp,
    timeframe,
):
    """
    Determine which candle a timestamp belongs to.

    All calculations are performed in New York time.
    """

    timestamp = pd.Timestamp(
        timestamp
    )

    if timestamp.tzinfo is None:

        timestamp = timestamp.tz_localize(
            "UTC"
        )

    timestamp = timestamp.tz_convert(
        NEW_YORK_TIMEZONE
    )

    if timeframe == "1m":

        return timestamp.floor(
            "min"
        )

    if timeframe == "5m":

        minute = (
            timestamp.minute
        )

        bucket_minute = (
            minute // 5
        ) * 5

        return timestamp.replace(
            minute=bucket_minute,
            second=0,
            microsecond=0,
        )

    if timeframe == "30m":

        minute = (
            timestamp.minute
        )

        bucket_minute = (
            minute // 30
        ) * 30

        return timestamp.replace(
            minute=bucket_minute,
            second=0,
            microsecond=0,
        )

    if timeframe == "1h":

        return timestamp.floor(
            "h"
        )

    if timeframe == "1d":

        return timestamp.normalize()

    if timeframe == "1w":

        return (
            timestamp
            - pd.Timedelta(
                days=timestamp.weekday()
            )
        ).normalize()

    raise ValueError(
        f"Unsupported timeframe: {timeframe}"
    )


# ============================================================
# UPDATE CURRENT CANDLE
# ============================================================

def update_current_candle(
    current_candle,
    price,
    timestamp,
    volume=0.0,
    trade_count=0,
):
    """
    Update the currently forming candle.

    The open never changes.

    Close becomes the newest live price.

    High/low expand when necessary.
    """

    price = float(price)

    if current_candle is None:

        bucket = (
            timestamp
        )

        return {
            "timestamp": bucket,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": float(volume),
            "trade_count": int(
                trade_count
            ),
        }

    current_candle["high"] = max(
        float(current_candle["high"]),
        price,
    )

    current_candle["low"] = min(
        float(current_candle["low"]),
        price,
    )

    current_candle["close"] = price

    current_candle["volume"] += (
        float(volume)
    )

    current_candle["trade_count"] += (
        int(trade_count)
    )

    return current_candle


# ============================================================
# REQUIRED EMA PERIODS
# ============================================================

def required_ema_periods(
    strategies,
):
    periods = set()

    for strategy in strategies:

        fast, slow = EMA_PAIRS[
            strategy - 1
        ]

        periods.add(fast)
        periods.add(slow)

    return sorted(
        periods
    )