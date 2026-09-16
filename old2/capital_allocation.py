# capital_allocation.py

import math
import numpy as np


# ============================================================
# DAILY STARTING BALANCE
# ============================================================

def create_daily_balance_state():
    """
    Create empty daily capital state.
    """

    return {
        "trading_date": None,
        "starting_balance": None,
    }


def set_daily_starting_balance(
    state,
    trading_date,
    starting_balance,
):
    """
    Store the Alpaca account balance used for the current
    trading day.

    This value remains fixed for the entire trading day.
    """

    if starting_balance is None:
        raise ValueError("starting_balance cannot be None")

    starting_balance = float(starting_balance)

    if not np.isfinite(starting_balance):
        raise ValueError("starting_balance must be finite")

    if starting_balance < 0:
        raise ValueError(
            "starting_balance cannot be negative"
        )

    state["trading_date"] = trading_date
    state["starting_balance"] = starting_balance

    return state


def get_daily_starting_balance(state):
    """
    Return the fixed starting balance for the current day.
    """

    balance = state.get("starting_balance")

    if balance is None:
        return None

    return float(balance)


# ============================================================
# DOLLAR ALLOCATION
# ============================================================

def calculate_allocated_dollars(
    starting_balance,
    contribution_percent,
):
    """
    Calculate the dollar amount allocated to a method.

    Example:

        Starting balance = $10,000
        Contribution     = 25%

        Allocation = $2,500
    """

    if starting_balance is None:
        return 0.0

    if not np.isfinite(starting_balance):
        return 0.0

    if not np.isfinite(contribution_percent):
        return 0.0

    if starting_balance <= 0:
        return 0.0

    if contribution_percent <= 0:
        return 0.0

    return (
        starting_balance
        * contribution_percent
        / 100.0
    )


# ============================================================
# SHARE QUANTITY
# ============================================================

def calculate_share_quantity(
    allocated_dollars,
    entry_price,
):
    """
    Calculate whole-share quantity.

    Fractional shares are not allowed.

    quantity = floor(allocated_dollars / entry_price)
    """

    if allocated_dollars is None:
        return 0

    if entry_price is None:
        return 0

    allocated_dollars = float(allocated_dollars)
    entry_price = float(entry_price)

    if not np.isfinite(allocated_dollars):
        return 0

    if not np.isfinite(entry_price):
        return 0

    if allocated_dollars <= 0:
        return 0

    if entry_price <= 0:
        return 0

    return int(
        math.floor(
            allocated_dollars / entry_price
        )
    )


# ============================================================
# COMPLETE POSITION ALLOCATION
# ============================================================

def calculate_position_allocation(
    starting_balance,
    contribution_percent,
    entry_price,
):
    """
    Calculate the complete position allocation for one method.

    Returns:

        contribution
        allocated dollars
        share quantity
        actual position value
        unused dollars
    """

    allocated_dollars = calculate_allocated_dollars(
        starting_balance,
        contribution_percent,
    )

    share_quantity = calculate_share_quantity(
        allocated_dollars,
        entry_price,
    )

    actual_position_value = (
        share_quantity * float(entry_price)
        if share_quantity > 0
        else 0.0
    )

    unused_dollars = (
        allocated_dollars
        - actual_position_value
    )

    return {
        "starting_balance": float(starting_balance),
        "contribution_percent": float(
            contribution_percent
        ),

        "allocated_dollars": float(
            allocated_dollars
        ),

        "entry_price": float(entry_price),

        "share_quantity": int(
            share_quantity
        ),

        "actual_position_value": float(
            actual_position_value
        ),

        "unused_dollars": float(
            unused_dollars
        ),
    }


# ============================================================
# METHOD ALLOCATION
# ============================================================

def calculate_method_allocation(
    method_id,
    starting_balance,
    contribution_percent,
    entry_price,
):
    """
    Calculate allocation information for one method.
    """

    allocation = calculate_position_allocation(
        starting_balance=starting_balance,
        contribution_percent=contribution_percent,
        entry_price=entry_price,
    )

    allocation["method_id"] = method_id

    return allocation


# ============================================================
# ALL METHOD ALLOCATIONS
# ============================================================

def calculate_allocation_for_methods(
    starting_balance,
    contributions,
    entry_prices,
):
    """
    Calculate allocations for all methods.

    contributions:
        {
            method_id: contribution_percent,
            ...
        }

    entry_prices:
        {
            method_id: entry_price,
            ...
        }

    Returns:

        {
            method_id: allocation,
            ...
        }
    """

    allocations = {}

    for method_id, contribution in contributions.items():

        entry_price = entry_prices.get(method_id)

        if entry_price is None:
            continue

        allocations[method_id] = calculate_method_allocation(
            method_id=method_id,
            starting_balance=starting_balance,
            contribution_percent=contribution,
            entry_price=entry_price,
        )

    return allocations


# ============================================================
# TRADABLE METHOD ALLOCATIONS
# ============================================================

def calculate_tradable_allocations(
    starting_balance,
    contributions,
    entry_prices,
    tradable_methods,
):
    """
    Calculate allocations only for methods that are currently
    allowed to trade.

    tradable_methods comes from contributions.py.
    """

    allocations = {}

    for method_id in tradable_methods:

        contribution = contributions.get(
            method_id,
            0.0,
        )

        entry_price = entry_prices.get(
            method_id
        )

        if entry_price is None:
            continue

        allocation = calculate_method_allocation(
            method_id=method_id,
            starting_balance=starting_balance,
            contribution_percent=contribution,
            entry_price=entry_price,
        )

        # A zero-share position cannot be traded.
        if allocation["share_quantity"] <= 0:
            continue

        allocations[method_id] = allocation

    return allocations


# ============================================================
# TOTAL ALLOCATION
# ============================================================

def calculate_total_allocated_dollars(
    allocations,
):
    """
    Calculate the total dollars allocated across methods.

    Note that this uses allocated dollars, not actual position
    value after whole-share rounding.
    """

    if not allocations:
        return 0.0

    return float(
        sum(
            allocation["allocated_dollars"]
            for allocation in allocations.values()
        )
    )


def calculate_total_position_value(
    allocations,
):
    """
    Calculate actual position value after whole-share rounding.
    """

    if not allocations:
        return 0.0

    return float(
        sum(
            allocation["actual_position_value"]
            for allocation in allocations.values()
        )
    )


# ============================================================
# VALIDATION
# ============================================================

def validate_allocations(
    starting_balance,
    allocations,
):
    """
    Validate that actual allocated position value does not
    exceed the daily starting balance.
    """

    total_position_value = (
        calculate_total_position_value(
            allocations
        )
    )

    return {
        "starting_balance": float(
            starting_balance
        ),

        "total_position_value": float(
            total_position_value
        ),

        "remaining_balance": float(
            starting_balance
            - total_position_value
        ),

        "within_balance": (
            total_position_value
            <= starting_balance
        ),
    }