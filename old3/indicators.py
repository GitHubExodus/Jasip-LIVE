# indicators.py

from collections import deque

import numpy as np
import pandas as pd

from old3.config import (
    EMA_PERIODS,
    EMA_PAIRS,
    ROC_PERIOD,
    GREEN_CANDLE_WINDOW,
    RED_CANDLE_WINDOW,
)


# ============================================================
# BASIC CALCULATIONS
# ============================================================

def ema_next(previous_ema, close, period):
    alpha = 2.0 / (period + 1.0)
    return alpha * close + (1.0 - alpha) * previous_ema


def roc(current, old):
    if old == 0:
        return np.nan

    return (current - old) / old * 100.0


def candle_change(open_, close):
    if open_ == 0:
        return np.nan

    return (close - open_) / open_ * 100.0


def crossover_price(
    fast_previous,
    slow_previous,
    fast_period,
    slow_period,
):
    fast_alpha = 2.0 / (fast_period + 1.0)
    slow_alpha = 2.0 / (slow_period + 1.0)

    return (
        (1.0 - slow_alpha) * slow_previous
        - (1.0 - fast_alpha) * fast_previous
    ) / (fast_alpha - slow_alpha)


# ============================================================
# INITIAL EMA
# ============================================================

def calculate_ema(values, period):
    values = np.asarray(values, dtype=np.float64)

    result = np.empty(len(values), dtype=np.float64)

    if len(values) == 0:
        return result

    result[0] = values[0]

    alpha = 2.0 / (period + 1.0)

    for i in range(1, len(values)):
        result[i] = (
            alpha * values[i]
            + (1.0 - alpha) * result[i - 1]
        )

    return result


# ============================================================
# ROLLING CANDLE AVERAGE
# ============================================================

class RollingCandleAverage:

    def __init__(self, window, positive):
        self.window = window
        self.positive = positive
        self.values = deque()
        self.total = 0.0

    def valid(self, value):
        if np.isnan(value):
            return False

        return value > 0 if self.positive else value < 0

    def add(self, value):
        if not self.valid(value):
            return

        if len(self.values) >= self.window:
            self.total -= self.values.popleft()

        self.values.append(value)
        self.total += value

    def replace(self, old_value, new_value):
        old_valid = self.valid(old_value)
        new_valid = self.valid(new_value)

        if old_valid:
            self.values.pop()
            self.total -= old_value

        if new_valid:
            self.values.append(new_value)
            self.total += new_value

    def average(self):
        if not self.values:
            return np.nan

        return self.total / len(self.values)


# ============================================================
# INDICATOR STATE
# ============================================================

class IndicatorState:

    def __init__(self, data):
        self.data = data.reset_index(drop=True).copy()

        self.green = RollingCandleAverage(
            GREEN_CANDLE_WINDOW,
            True,
        )

        self.red = RollingCandleAverage(
            RED_CANDLE_WINDOW,
            False,
        )

        self._initialize()

    # --------------------------------------------------------
    # STARTUP
    # --------------------------------------------------------

    def _initialize(self):
        self._add_columns()

        close = self.data["close"].to_numpy(dtype=float)

        for period in EMA_PERIODS:
            self.data[f"ema_{period}"] = calculate_ema(
                close,
                period,
            )

        self._initialize_candle_averages()
        self._calculate_initial_roc()
        self._calculate_initial_cross_prices()

    def _add_columns(self):
        for period in EMA_PERIODS:
            self.data[f"ema_{period}"] = np.nan

        self.data["roc"] = np.nan
        self.data["avg_green"] = np.nan
        self.data["avg_red"] = np.nan

        for fast, slow in EMA_PAIRS:
            self.data[
                f"cross_price_{fast}_{slow}"
            ] = np.nan

    # --------------------------------------------------------
    # INITIAL CANDLE AVERAGES
    # --------------------------------------------------------

    def _initialize_candle_averages(self):
        for i in range(len(self.data)):
            change = candle_change(
                self.data["open"].iloc[i],
                self.data["close"].iloc[i],
            )

            self.green.add(change)
            self.red.add(change)

            self.data.loc[i, "avg_green"] = (
                self.green.average()
            )

            self.data.loc[i, "avg_red"] = (
                self.red.average()
            )

    # --------------------------------------------------------
    # INITIAL ROC
    # --------------------------------------------------------

    def _calculate_initial_roc(self):
        close = self.data["close"].to_numpy(dtype=float)

        for i in range(ROC_PERIOD, len(close)):
            self.data.loc[i, "roc"] = roc(
                close[i],
                close[i - ROC_PERIOD],
            )

    # --------------------------------------------------------
    # INITIAL CROSSOVER PRICES
    # --------------------------------------------------------

    def _calculate_initial_cross_prices(self):
        for i in range(1, len(self.data)):
            self._calculate_cross_prices(i)

    # --------------------------------------------------------
    # UPDATE
    # --------------------------------------------------------

    def update(self, bar):
        bar = clean_bar(bar)

        if bar is None:
            return

        if self.data.empty:
            self.data = pd.DataFrame([bar])

            self.green = RollingCandleAverage(
                GREEN_CANDLE_WINDOW,
                True,
            )

            self.red = RollingCandleAverage(
                RED_CANDLE_WINDOW,
                False,
            )

            self._initialize()
            return

        last_timestamp = self.data["timestamp"].iloc[-1]

        if bar["timestamp"] < last_timestamp:
            return

        if bar["timestamp"] == last_timestamp:
            self._replace_current(bar)
        else:
            self._append_new(bar)

    # --------------------------------------------------------
    # REPLACE CURRENT BAR
    # --------------------------------------------------------

    def _replace_current(self, bar):
        index = len(self.data) - 1

        old_change = candle_change(
            self.data["open"].iloc[index],
            self.data["close"].iloc[index],
        )

        new_change = candle_change(
            bar["open"],
            bar["close"],
        )

        for key, value in bar.items():
            self.data.loc[index, key] = value

        self.green.replace(
            old_change,
            new_change,
        )

        self.red.replace(
            old_change,
            new_change,
        )

        self._calculate_current(index)

    # --------------------------------------------------------
    # APPEND NEW BAR
    # --------------------------------------------------------

    def _append_new(self, bar):
        index = len(self.data)

        row = bar.copy()

        # EMA
        for period in EMA_PERIODS:
            previous = self.data[
                f"ema_{period}"
            ].iloc[-1]

            row[f"ema_{period}"] = ema_next(
                previous,
                bar["close"],
                period,
            )

        # ROC
        if index >= ROC_PERIOD:
            old_close = self.data["close"].iloc[
                index - ROC_PERIOD
            ]

            row["roc"] = roc(
                bar["close"],
                old_close,
            )
        else:
            row["roc"] = np.nan

        # Candle averages
        change = candle_change(
            bar["open"],
            bar["close"],
        )

        self.green.add(change)
        self.red.add(change)

        row["avg_green"] = self.green.average()
        row["avg_red"] = self.red.average()

        # Crossover prices
        for fast, slow in EMA_PAIRS:
            row[
                f"cross_price_{fast}_{slow}"
            ] = crossover_price(
                self.data[
                    f"ema_{fast}"
                ].iloc[-1],
                self.data[
                    f"ema_{slow}"
                ].iloc[-1],
                fast,
                slow,
            )

        self.data.loc[index] = row

    # --------------------------------------------------------
    # CURRENT BAR
    # --------------------------------------------------------

    def _calculate_current(self, index):
        previous = index - 1
        close = self.data["close"].iloc[index]

        # EMA
        for period in EMA_PERIODS:
            column = f"ema_{period}"

            self.data.loc[index, column] = ema_next(
                self.data[column].iloc[previous],
                close,
                period,
            )

        # ROC
        if index >= ROC_PERIOD:
            old_close = self.data["close"].iloc[
                index - ROC_PERIOD
            ]

            self.data.loc[index, "roc"] = roc(
                close,
                old_close,
            )
        else:
            self.data.loc[index, "roc"] = np.nan

        # Candle averages
        self.data.loc[index, "avg_green"] = (
            self.green.average()
        )

        self.data.loc[index, "avg_red"] = (
            self.red.average()
        )

        # Crossover prices
        self._calculate_cross_prices(index)

    # --------------------------------------------------------
    # CROSSOVER PRICES
    # --------------------------------------------------------

    def _calculate_cross_prices(self, index):
        previous = index - 1

        for fast, slow in EMA_PAIRS:
            self.data.loc[
                index,
                f"cross_price_{fast}_{slow}",
            ] = crossover_price(
                self.data[
                    f"ema_{fast}"
                ].iloc[previous],
                self.data[
                    f"ema_{slow}"
                ].iloc[previous],
                fast,
                slow,
            )

    # --------------------------------------------------------
    # OUTPUT
    # --------------------------------------------------------

    def latest(self):
        return self.data.iloc[-1]

    def values(self):
        return self.latest().to_dict()

    def dataframe(self):
        return self.data


# ============================================================
# BAR CLEANING
# ============================================================

def clean_bar(bar):
    if isinstance(bar, pd.DataFrame):
        if bar.empty:
            return None

        bar = bar.iloc[-1]

    if isinstance(bar, pd.Series):
        bar = bar.to_dict()

    if not isinstance(bar, dict):
        return None

    required = (
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "trade_count",
        "vwap",
    )

    if any(column not in bar for column in required):
        return None

    return {
        "timestamp": pd.Timestamp(bar["timestamp"]),
        "open": float(bar["open"]),
        "high": float(bar["high"]),
        "low": float(bar["low"]),
        "close": float(bar["close"]),
        "volume": float(bar["volume"]),
        "trade_count": float(bar["trade_count"]),
        "vwap": float(bar["vwap"]),
    }