# trade_levels.py

import numpy as np

from old2.config import ENTRY_RANGE_MULTIPLIER


# ============================================================
# CALCULATE TRADE LEVELS
# ============================================================

def calculate_trade_levels(
    entry_price,
    green_average,
    red_average,
    stop_loss_multiplier,
    risk_reward,
):
    """
    Input:
        entry_price: strategy entry price
        green_average: average green candle percentage
        red_average: average red candle percentage
        stop_loss_multiplier: stop-loss multiplier
        risk_reward: risk/reward multiplier

    Description:
        Calculates independent SL and TP distances.

        SL:
            entry × red_average × stop_loss_multiplier

        TP:
            entry × green_average × risk_reward
            × stop_loss_multiplier

    Output:
        dictionary containing trade price levels
    """

    if any(
        np.isnan(value)
        for value in (
            entry_price,
            green_average,
            red_average,
        )
    ):
        return None

    if entry_price <= 0:
        return None

    # Base distances from the two separate candle averages.
    base_stop_distance = (
        entry_price
        * red_average
        / 100.0
    )

    base_take_profit_distance = (
        entry_price
        * green_average
        / 100.0
    )

    # Apply the stop-loss multiplier to BOTH.
    stop_distance = (
        base_stop_distance
        * stop_loss_multiplier
    )

    take_profit_distance = (
        base_take_profit_distance
        * risk_reward
        * stop_loss_multiplier
    )

    stop_loss_price = (
        entry_price
        - stop_distance
    )

    take_profit_price = (
        entry_price
        + take_profit_distance
    )

    return {
        "entry_price": entry_price,
        "stop_loss_price": stop_loss_price,
        "take_profit_price": take_profit_price,
        "stop_distance": stop_distance,
        "take_profit_distance": take_profit_distance,
        "base_stop_distance": base_stop_distance,
        "base_take_profit_distance": base_take_profit_distance,
    }

# ============================================================
# ENTRY ELIGIBILITY RANGE
# ============================================================

def calculate_entry_range(
    current_price,
    green_average,
    red_average,
):
    """
    Input:
        current_price: current relevant market price
        green_average: average green candle percentage
        red_average: average red candle percentage

    Description:
        Calculates the allowed entry-price range.

        Upper limit:
            current price + (15 × green average)

        Lower limit:
            current price - (15 × red average)

    Output:
        dictionary containing lower and upper entry limits
    """

    if any(
        np.isnan(value)
        for value in (
            current_price,
            green_average,
            red_average,
        )
    ):
        return None

    upper_limit = (
        current_price
        * (
            1.0
            + (
                ENTRY_RANGE_MULTIPLIER
                * green_average
                / 100.0
            )
        )
    )

    lower_limit = (
        current_price
        * (
            1.0
            - (
                ENTRY_RANGE_MULTIPLIER
                * red_average
                / 100.0
            )
        )
    )

    return {
        "lower": lower_limit,
        "upper": upper_limit,
    }


# ============================================================
# CHECK ENTRY ELIGIBILITY
# ============================================================

def is_entry_eligible(
    entry_price,
    current_price,
    green_average,
    red_average,
):
    """
    Input:
        entry_price: calculated strategy entry price
        current_price: current market price
        green_average: average green candle percentage
        red_average: average red candle percentage

    Description:
        Determines whether the calculated entry price is
        close enough to the current price to create a
        pending Alpaca entry.

    Output:
        bool
    """

    entry_range = calculate_entry_range(
        current_price=current_price,
        green_average=green_average,
        red_average=red_average,
    )

    if entry_range is None:
        return False

    return (
        entry_range["lower"]
        <= entry_price
        <= entry_range["upper"]
    )


# ============================================================
# GET COMPLETE TRADE SETUP
# ============================================================

def calculate_trade_setup(
    entry_price,
    current_price,
    green_average,
    red_average,
    stop_loss_multiplier,
    risk_reward,
):
    """
    Input:
        entry_price: strategy entry price
        current_price: current market price
        green_average: average green candle percentage
        red_average: average red candle percentage
        stop_loss_multiplier: SL multiplier
        risk_reward: RR ratio

    Description:
        Calculates the complete trade setup and determines
        whether the entry is inside the allowed entry range.

        This does NOT place an order.

    Output:
        dictionary containing:
            entry price
            stop-loss price
            take-profit price
            entry range
            eligibility
    """

    levels = calculate_trade_levels(
        entry_price=entry_price,
        green_average=green_average,
        red_average=red_average,
        stop_loss_multiplier=stop_loss_multiplier,
        risk_reward=risk_reward,
    )

    if levels is None:
        return None

    entry_range = calculate_entry_range(
        current_price=current_price,
        green_average=green_average,
        red_average=red_average,
    )

    eligible = is_entry_eligible(
        entry_price=entry_price,
        current_price=current_price,
        green_average=green_average,
        red_average=red_average,
    )

    return {
        **levels,
        "entry_range_lower": entry_range["lower"],
        "entry_range_upper": entry_range["upper"],
        "entry_eligible": eligible,
    }