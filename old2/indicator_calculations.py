# indicator_calculations.py

import numpy as np
from numba import njit


# ============================================================
# EMA
# ============================================================

@njit
def calculate_initial_ema(values, period):
    """
    Input:
        values: 1D numpy array of prices
        period: EMA period

    Description:
        Calculates the initial EMA series.

    Output:
        1D numpy array containing EMA values
    """

    values = np.asarray(values, dtype=np.float64)

    result = np.empty(
        len(values),
        dtype=np.float64,
    )

    result[:] = np.nan

    if len(values) < period:
        return result

    alpha = 2.0 / (period + 1.0)

    # Initial EMA uses SMA.
    total = 0.0

    for i in range(period):
        total += values[i]

    result[period - 1] = total / period

    # Incremental EMA calculation.
    for i in range(period, len(values)):
        result[i] = (
            alpha * values[i]
            + (1.0 - alpha) * result[i - 1]
        )

    return result


@njit
def update_ema(previous_ema, price, period):
    """
    Input:
        previous_ema: previous EMA value
        price: newest calculation-bar price
        period: EMA period

    Description:
        Calculates one new EMA value.

    Output:
        float
    """

    alpha = 2.0 / (period + 1.0)

    return (
        alpha * price
        + (1.0 - alpha) * previous_ema
    )


# ============================================================
# ROC
# ============================================================

@njit
def calculate_roc(values, period):
    """
    Input:
        values: 1D numpy array of prices
        period: ROC period

    Description:
        Calculates Rate of Change as a percentage.

    Output:
        1D numpy array
    """

    values = np.asarray(values, dtype=np.float64)

    result = np.empty(
        len(values),
        dtype=np.float64,
    )

    result[:] = np.nan

    if len(values) <= period:
        return result

    for i in range(period, len(values)):
        previous = values[i - period]

        if previous == 0.0:
            result[i] = np.nan
        else:
            result[i] = (
                (values[i] - previous)
                / previous
            ) * 100.0

    return result


@njit
def update_roc(previous_price, current_price):
    """
    Input:
        previous_price: price from ROC_PERIOD bars ago
        current_price: current calculation-bar price

    Description:
        Calculates the newest ROC value.

    Output:
        float
    """

    if previous_price == 0.0:
        return np.nan

    return (
        (current_price - previous_price)
        / previous_price
    ) * 100.0


# ============================================================
# GREEN / RED CANDLE VALUES
# ============================================================

@njit
def calculate_candle_change(open_price, close_price):
    """
    Input:
        open_price: candle open
        close_price: candle close

    Description:
        Calculates the candle's percentage movement.
        Green candles return positive values.
        Red candles return positive magnitude values.

    Output:
        tuple:
            (green_change, red_change)
    """

    if open_price == 0.0:
        return np.nan, np.nan

    change = (
        (close_price - open_price)
        / open_price
    ) * 100.0

    if change > 0.0:
        return change, np.nan

    if change < 0.0:
        return np.nan, -change

    return np.nan, np.nan


# ============================================================
# INITIAL CANDLE AVERAGES
# ============================================================

@njit
def calculate_initial_candle_averages(
    opens,
    closes,
    window,
):
    """
    Input:
        opens: 1D numpy array of candle opens
        closes: 1D numpy array of candle closes
        window: number of most recent green/red candles

    Description:
        Finds the most recent `window` individual green candles
        and most recent `window` individual red candles and
        calculates their average percentage movement.

    Output:
        tuple:
            (green_average, red_average)
    """

    green_sum = 0.0
    red_sum = 0.0

    green_count = 0
    red_count = 0

    # Work backwards because we only need the most recent
    # qualifying candles.
    for i in range(len(opens) - 1, -1, -1):

        if opens[i] == 0.0:
            continue

        change = (
            (closes[i] - opens[i])
            / opens[i]
        ) * 100.0

        if change > 0.0 and green_count < window:
            green_sum += change
            green_count += 1

        elif change < 0.0 and red_count < window:
            red_sum += -change
            red_count += 1

        if (
            green_count >= window
            and red_count >= window
        ):
            break

    if green_count > 0:
        green_average = green_sum / green_count
    else:
        green_average = np.nan

    if red_count > 0:
        red_average = red_sum / red_count
    else:
        red_average = np.nan

    return green_average, red_average


# ============================================================
# ROLLING CANDLE STATE
# ============================================================

@njit
def add_candle_to_rolling_state(
    open_price,
    close_price,
    green_values,
    red_values,
    green_sum,
    red_sum,
    green_index,
    red_index,
    green_count,
    red_count,
):
    """
    Input:
        open_price: newest candle open
        close_price: newest candle close
        green_values: fixed-size green candle queue
        red_values: fixed-size red candle queue
        green_sum: current green queue sum
        red_sum: current red queue sum
        green_index: next green queue position
        red_index: next red queue position
        green_count: number of green values currently stored
        red_count: number of red values currently stored

    Description:
        Adds the newest candle to the appropriate rolling queue
        and removes the oldest value when the queue is full.

    Output:
        tuple containing the updated rolling state
    """

    if open_price == 0.0:
        return (
            green_sum,
            red_sum,
            green_index,
            red_index,
            green_count,
            red_count,
        )

    change = (
        (close_price - open_price)
        / open_price
    ) * 100.0

    # --------------------------------------------------------
    # GREEN
    # --------------------------------------------------------

    if change > 0.0:

        if green_count == len(green_values):
            green_sum -= green_values[green_index]

        else:
            green_count += 1

        green_values[green_index] = change
        green_sum += change

        green_index += 1

        if green_index >= len(green_values):
            green_index = 0

    # --------------------------------------------------------
    # RED
    # --------------------------------------------------------

    elif change < 0.0:

        change = -change

        if red_count == len(red_values):
            red_sum -= red_values[red_index]

        else:
            red_count += 1

        red_values[red_index] = change
        red_sum += change

        red_index += 1

        if red_index >= len(red_values):
            red_index = 0

    return (
        green_sum,
        red_sum,
        green_index,
        red_index,
        green_count,
        red_count,
    )


# ============================================================
# ROLLING AVERAGES
# ============================================================

@njit
def get_rolling_candle_averages(
    green_sum,
    red_sum,
    green_count,
    red_count,
):
    """
    Input:
        green_sum: sum of stored green candle movements
        red_sum: sum of stored red candle movements
        green_count: number of stored green candles
        red_count: number of stored red candles

    Description:
        Calculates the current rolling green and red averages.

    Output:
        tuple:
            (green_average, red_average)
    """

    if green_count > 0:
        green_average = green_sum / green_count
    else:
        green_average = np.nan

    if red_count > 0:
        red_average = red_sum / red_count
    else:
        red_average = np.nan

    return green_average, red_average