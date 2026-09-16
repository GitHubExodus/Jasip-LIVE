# contributions.py

import numpy as np
import pandas as pd

from old2.config import ROC_PERIOD

# ============================================================
# LATEST EQUITY ROC
# ============================================================

def calculate_method_roc(equity_curve):
    """
    Calculate ROC over ROC_PERIOD completed equity rows.

    ROC is based on standalone method equity.
    Contribution has no effect on this calculation.

    Returns:
        ROC percentage, or None if insufficient data.
    """

    if equity_curve is None or len(equity_curve) <= ROC_PERIOD:
        return None

    current_equity = equity_curve[-1]["equity"]
    previous_equity = equity_curve[-1 - ROC_PERIOD]["equity"]

    if previous_equity == 0:
        return None

    return (
        (current_equity / previous_equity) - 1.0
    ) * 100.0


# ============================================================
# COLLECT METHOD ROCS
# ============================================================

def calculate_all_method_rocs(equity_curves):
    """
    Calculate ROC for every method.
    """

    method_rocs = {}

    for method_id, equity_curve in equity_curves.items():
        roc = calculate_method_roc(equity_curve)

        if roc is None:
            roc = 0.0

        method_rocs[method_id] = roc

    return method_rocs

# ============================================================
# CALCULATE CONTRIBUTIONS
# ============================================================

def calculate_contributions(method_rocs):
    """
    Convert positive method ROC values into contribution
    percentages.

    Rules:

        ROC <= 0  -> contribution = 0
        ROC > 0   -> contribution = ROC / total_positive_ROC

    Therefore all positive contributions sum to 100%.
    """

    method_ids = list(method_rocs.keys())

    if not method_ids:
        return {}

    positive_rocs = np.zeros(
        len(method_ids),
        dtype=np.float64,
    )

    for i, method_id in enumerate(method_ids):

        roc = method_rocs[method_id]

        if np.isfinite(roc) and roc > 0:
            positive_rocs[i] = roc

    total_positive_roc = np.sum(
        positive_rocs
    )

    contributions = {}

    if total_positive_roc <= 0:

        for method_id in method_ids:
            contributions[method_id] = 0.0

        return contributions

    normalized = (
        positive_rocs
        / total_positive_roc
    )

    for i, method_id in enumerate(method_ids):
        contributions[method_id] = (
            float(normalized[i]) * 100.0
        )

    return contributions


# ============================================================
# RANK METHODS
# ============================================================

def rank_methods_by_contribution(contributions):
    """
    Rank methods from highest contribution to lowest.
    """

    return sorted(
        contributions.keys(),
        key=lambda method_id: contributions[method_id],
        reverse=True,
    )


# ============================================================
# GET TOP TRADABLE METHODS
# ============================================================

def get_top_tradable_methods(
    contributions,
    method_rocs,
    max_methods=20,
):
    """
    Return the top methods that:

        1. Have positive ROC.
        2. Have positive contribution.
        3. Are within the top max_methods.

    Returns a list ordered from highest contribution
    to lowest contribution.
    """

    eligible = [
        method_id
        for method_id in contributions
        if (
            contributions[method_id] > 0
            and np.isfinite(method_rocs.get(method_id, np.nan))
            and method_rocs[method_id] > 0
        )
    ]

    eligible.sort(
        key=lambda method_id: contributions[method_id],
        reverse=True,
    )

    return eligible[:max_methods]


# ============================================================
# CONTRIBUTION SNAPSHOT
# ============================================================

def create_contribution_snapshot(
    timestamp,
    contributions,
):
    """
    Create one contribution snapshot.

    Every method is represented as a column.
    """

    row = {
        "timestamp": timestamp
    }

    for method_id, contribution in contributions.items():
        row[method_id] = contribution

    return row


# ============================================================
# APPEND CONTRIBUTION SNAPSHOT
# ============================================================

def add_contribution_snapshot(
    contribution_data,
    timestamp,
    contributions,
):
    """
    Add a new contribution snapshot to the shared
    contribution DataFrame.

    Every method remains a column.
    """

    row = create_contribution_snapshot(
        timestamp,
        contributions,
    )

    new_row = pd.DataFrame([row])

    if contribution_data is None:
        return new_row

    if contribution_data.empty:
        return new_row

    result = pd.concat(
        [
            contribution_data,
            new_row,
        ],
        ignore_index=True,
    )

    return result


# ============================================================
# GET LATEST CONTRIBUTIONS
# ============================================================

def get_latest_contributions(
    contribution_data,
):
    """
    Return the most recent contribution snapshot.

    Returns:

        {
            method_id: contribution_percent,
            ...
        }
    """

    if contribution_data is None:
        return {}

    if contribution_data.empty:
        return {}

    latest = contribution_data.iloc[-1]

    contributions = {}

    for column in contribution_data.columns:

        if column == "timestamp":
            continue

        value = latest[column]

        if pd.isna(value):
            value = 0.0

        contributions[column] = float(value)

    return contributions


# ============================================================
# GET METHOD CONTRIBUTION
# ============================================================

def get_method_contribution(
    contribution_data,
    method_id,
):
    """
    Get the latest contribution for one method.
    """

    contributions = get_latest_contributions(
        contribution_data
    )

    return float(
        contributions.get(method_id, 0.0)
    )


# ============================================================
# BUILD CONTRIBUTION STATE
# ============================================================

def calculate_contribution_state(
    equity_curves,
    timestamp,
):
    """
    Calculate the complete contribution state.

    Returns:

        method_rocs
        contributions
        ranked_methods
        tradable_methods
        snapshot
    """

    method_rocs = calculate_all_method_rocs(
        equity_curves
    )

    contributions = calculate_contributions(
        method_rocs
    )

    ranked_methods = rank_methods_by_contribution(
        contributions
    )

    tradable_methods = get_top_tradable_methods(
        contributions,
        method_rocs,
        max_methods=20,
    )

    snapshot = create_contribution_snapshot(
        timestamp,
        contributions,
    )

    return {
        "timestamp": timestamp,

        "method_rocs": method_rocs,

        "contributions": contributions,

        "ranked_methods": ranked_methods,

        "tradable_methods": tradable_methods,

        "snapshot": snapshot,
    }


# ============================================================
# CHECK WHETHER METHOD IS TRADABLE
# ============================================================

def is_method_tradable(
    method_id,
    contribution_state,
):
    """
    Determine whether a method is currently allowed
    to place live trades.
    """

    return method_id in contribution_state[
        "tradable_methods"
    ]