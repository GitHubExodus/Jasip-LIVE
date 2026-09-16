# indicator_state.py

import numpy as np

from old2.config import (
    EMA_PERIODS,
    ROC_PERIOD,
    CANDLE_AVERAGE_WINDOW,
)

from old2.indicator_calculations import (
    calculate_initial_ema,
    update_ema,
    calculate_initial_candle_averages,
    add_candle_to_rolling_state,
    get_rolling_candle_averages,
)


# ============================================================
# INITIALIZE INDICATOR STATE
# ============================================================

def initialize_indicator_state(data):
    """
    Input:
        data: timeframe DataFrame

    Description:
        Calculates the initial indicator values and creates
        the rolling state required for future incremental updates.

    Output:
        dictionary containing indicator state
    """

    if data.empty:
        return None

    closes = data["close"].to_numpy(
        dtype=np.float64
    )

    opens = data["open"].to_numpy(
        dtype=np.float64
    )

    state = {
        "ema": {},
        "roc": np.nan,
        "green_values": np.zeros(
            CANDLE_AVERAGE_WINDOW,
            dtype=np.float64,
        ),
        "red_values": np.zeros(
            CANDLE_AVERAGE_WINDOW,
            dtype=np.float64,
        ),
        "green_sum": 0.0,
        "red_sum": 0.0,
        "green_index": 0,
        "red_index": 0,
        "green_count": 0,
        "red_count": 0,
        "green_average": np.nan,
        "red_average": np.nan,
        "last_timestamp": None,
    }

    # --------------------------------------------------------
    # EMA
    # --------------------------------------------------------

    for period in EMA_PERIODS:

        ema_values = calculate_initial_ema(
            closes,
            period,
        )

        valid = ~np.isnan(ema_values)

        if np.any(valid):
            state["ema"][period] = ema_values[-1]
        else:
            state["ema"][period] = np.nan

    # --------------------------------------------------------
    # ROC
    # --------------------------------------------------------

    if len(closes) > ROC_PERIOD:

        previous_price = closes[-1 - ROC_PERIOD]
        current_price = closes[-1]

        if previous_price != 0:
            state["roc"] = (
                (current_price - previous_price)
                / previous_price
            ) * 100.0

    # --------------------------------------------------------
    # GREEN / RED CANDLE QUEUES
    # --------------------------------------------------------

    green_average, red_average = (
        calculate_initial_candle_averages(
            opens,
            closes,
            CANDLE_AVERAGE_WINDOW,
        )
    )

    state["green_average"] = green_average
    state["red_average"] = red_average

    # Build the actual rolling queues so future updates
    # can be performed incrementally.

    start_index = 0

    for i in range(len(data) - 1, -1, -1):

        if (
            state["green_count"] >= CANDLE_AVERAGE_WINDOW
            and state["red_count"] >= CANDLE_AVERAGE_WINDOW
        ):
            break

        if opens[i] == 0:
            continue

        change = (
            (closes[i] - opens[i])
            / opens[i]
        ) * 100.0

        if change > 0:

            if state["green_count"] < CANDLE_AVERAGE_WINDOW:

                index = (
                    CANDLE_AVERAGE_WINDOW
                    - 1
                    - state["green_count"]
                )

                state["green_values"][index] = change
                state["green_sum"] += change
                state["green_count"] += 1

        elif change < 0:

            change = -change

            if state["red_count"] < CANDLE_AVERAGE_WINDOW:

                index = (
                    CANDLE_AVERAGE_WINDOW
                    - 1
                    - state["red_count"]
                )

                state["red_values"][index] = change
                state["red_sum"] += change
                state["red_count"] += 1

    # Set the queue pointers so the next update replaces
    # the oldest stored value.

    if state["green_count"] >= CANDLE_AVERAGE_WINDOW:
        state["green_index"] = 0
    else:
        state["green_index"] = state["green_count"]

    if state["red_count"] >= CANDLE_AVERAGE_WINDOW:
        state["red_index"] = 0
    else:
        state["red_index"] = state["red_count"]

    state["last_timestamp"] = data["timestamp"].iloc[-1]

    return state


# ============================================================
# UPDATE INDICATOR STATE
# ============================================================

def update_indicator_state(
    state,
    data,
):
    """
    Input:
        state: existing indicator state
        data: updated timeframe DataFrame

    Description:
        Updates indicators using only newly available
        calculation bars. Historical indicator values are
        not recalculated.

    Output:
        updated indicator state
    """

    if state is None:
        return initialize_indicator_state(data)

    if data.empty:
        return state

    # --------------------------------------------------------
    # FIND NEW DATA
    # --------------------------------------------------------

    timestamps = data["timestamp"]

    last_timestamp = state["last_timestamp"]

    new_data = data[
        timestamps > last_timestamp
    ]

    if new_data.empty:
        return state

    # --------------------------------------------------------
    # UPDATE EACH NEW BAR
    # --------------------------------------------------------

    for i in range(len(new_data)):

        row = new_data.iloc[i]

        price = float(row["close"])

        timestamp = row["timestamp"]

        # ----------------------------------------------------
        # EMA
        # ----------------------------------------------------

        for period in EMA_PERIODS:

            previous_ema = state["ema"][period]

            if not np.isnan(previous_ema):

                state["ema"][period] = update_ema(
                    previous_ema,
                    price,
                    period,
                )

        # ----------------------------------------------------
        # CANDLE AVERAGES
        # ----------------------------------------------------

        (
            state["green_sum"],
            state["red_sum"],
            state["green_index"],
            state["red_index"],
            state["green_count"],
            state["red_count"],
        ) = add_candle_to_rolling_state(
            float(row["open"]),
            float(row["close"]),
            state["green_values"],
            state["red_values"],
            state["green_sum"],
            state["red_sum"],
            state["green_index"],
            state["red_index"],
            state["green_count"],
            state["red_count"],
        )

        # ----------------------------------------------------
        # ROC
        # ----------------------------------------------------

        current_position = (
            data.index[data["timestamp"] == timestamp]
        )

        if len(current_position) > 0:

            position = current_position[0]

            previous_position = position - ROC_PERIOD

            if previous_position >= 0:

                previous_price = float(
                    data.iloc[previous_position]["close"]
                )

                if previous_price != 0:

                    state["roc"] = (
                        (price - previous_price)
                        / previous_price
                    ) * 100.0

        state["last_timestamp"] = timestamp

    # --------------------------------------------------------
    # FINAL CANDLE AVERAGES
    # --------------------------------------------------------

    (
        state["green_average"],
        state["red_average"],
    ) = get_rolling_candle_averages(
        state["green_sum"],
        state["red_sum"],
        state["green_count"],
        state["red_count"],
    )

    return state


# ============================================================
# GET INDICATOR VALUE
# ============================================================

def get_indicator_value(
    state,
    indicator,
    period=None,
):
    """
    Input:
        state: indicator state
        indicator: indicator name
        period: indicator period when required

    Description:
        Retrieves a specific indicator value.

    Output:
        indicator value
    """

    if indicator == "ema":
        return state["ema"][period]

    if indicator == "roc":
        return state["roc"]

    if indicator == "green_average":
        return state["green_average"]

    if indicator == "red_average":
        return state["red_average"]

    raise ValueError(
        f"Unknown indicator: {indicator}"
    )


# ============================================================
# GET ALL INDICATORS
# ============================================================

def get_indicator_snapshot(state):
    """
    Input:
        state: indicator state

    Description:
        Returns the current indicator values as a simple
        snapshot for strategy calculations.

    Output:
        dictionary containing current indicator values
    """

    return {
        "ema": state["ema"].copy(),
        "roc": state["roc"],
        "green_average": state["green_average"],
        "red_average": state["red_average"],
    }