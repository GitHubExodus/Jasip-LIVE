# data.py

import pandas as pd

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from old3.config import TIMEZONE


def _clean(data):
    if data.empty:
        return data

    data = data.reset_index()

    if "symbol" in data.columns:
        data = data.drop(columns="symbol")

    data["timestamp"] = (
        pd.to_datetime(data["timestamp"], utc=True)
        .dt.tz_convert(TIMEZONE)
    )

    return (
        data
        .sort_values("timestamp")
        .drop_duplicates("timestamp", keep="last")
        .reset_index(drop=True)
    )


def _get_bars(client, symbol, timeframe, start=None, end=None, limit=None):
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=timeframe,
        start=start,
        end=end,
        limit=limit,
        feed="iex",
    )

    return _clean(client.get_stock_bars(request).df)


def load_initial(symbol, start, end=None):
    client = StockHistoricalDataClient()

    data_5m = _get_bars(
        client,
        symbol,
        TimeFrame(5, TimeFrameUnit.Minute),
        start=start,
        end=end,
    )

    data_30m = _get_bars(
        client,
        symbol,
        TimeFrame(30, TimeFrameUnit.Minute),
        start=start,
        end=end,
    )

    return {
        "5m": data_5m,
        "30m": data_30m,
        "day": build_day(data_30m),
    }


def update(symbol, data):
    client = StockHistoricalDataClient()

    latest_5m = _get_bars(
        client,
        symbol,
        TimeFrame(5, TimeFrameUnit.Minute),
        limit=1,
    )

    latest_30m = _get_bars(
        client,
        symbol,
        TimeFrame(30, TimeFrameUnit.Minute),
        limit=1,
    )

    data["5m"] = _update_current_bar(
        data["5m"],
        latest_5m,
    )

    data["30m"] = _update_current_bar(
        data["30m"],
        latest_30m,
    )

    data["day"] = build_day(data["30m"])

    return data


def _update_current_bar(old, new):
    if new.empty:
        return old

    new_bar = new.iloc[-1]

    if old.empty:
        return new.reset_index(drop=True)

    old_timestamp = old["timestamp"].iloc[-1]
    new_timestamp = new_bar["timestamp"]

    if new_timestamp < old_timestamp:
        return old

    if new_timestamp == old_timestamp:
        old = old.copy()
        old.iloc[-1] = new_bar
        return old

    return pd.concat(
        [old, new.tail(1)],
        ignore_index=True,
    )


def build_day(data_30m):
    if data_30m.empty:
        return data_30m.copy()

    data = data_30m.copy()
    data["date"] = data["timestamp"].dt.date

    return (
        data
        .groupby("date", sort=True)
        .agg(
            timestamp=("timestamp", "last"),
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            trade_count=("trade_count", "sum"),
            vwap=("vwap", "last"),
        )
        .reset_index(drop=True)
    )