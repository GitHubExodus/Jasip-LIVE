# equity_curves.py

import numpy as np
import pandas as pd


# ============================================================
# EQUITY CURVE CREATION
# ============================================================

def create_equity_curve(method_id, symbol):
    """
    Create an empty equity curve for one method.

    Equity starts at 1.0, representing 100% of starting capital.
    """

    return {
        "method_id": method_id,
        "symbol": symbol,
        "rows": [],
    }


# ============================================================
# EQUITY UPDATE
# ============================================================

def calculate_new_equity(previous_equity, trade_return_percent):
    """
    Apply a completed trade's percentage return to equity.

    Example:

        equity = 1.00
        trade return = +10%

        new equity = 1.10
    """

    return previous_equity * (
        1.0 + trade_return_percent / 100.0
    )


def add_completed_trade_to_equity(
    equity_curve,
    trade,
):
    """
    Add one completed trade to a method's equity curve.

    The equity curve stores:

        entry timestamp
        exit timestamp
        entry price
        exit price
        equity
        trade return
        method ID
        symbol
    """

    if trade is None:
        return equity_curve

    if trade.get("status") != "completed":
        return equity_curve

    trade_return = trade.get("return_percent")

    if trade_return is None:
        return equity_curve

    rows = equity_curve["rows"]

    # --------------------------------------------------------
    # Previous equity
    # --------------------------------------------------------

    if rows:
        previous_equity = float(rows[-1]["equity"])
    else:
        previous_equity = 1.0

    # --------------------------------------------------------
    # New equity
    # --------------------------------------------------------

    new_equity = calculate_new_equity(
        previous_equity,
        trade_return,
    )

    # --------------------------------------------------------
    # Store row
    # --------------------------------------------------------

    row = {
        "method_id": equity_curve["method_id"],
        "symbol": equity_curve["symbol"],

        "entry_timestamp": trade["entry_timestamp"],
        "exit_timestamp": trade["exit_timestamp"],

        "entry_price": trade["entry_price"],
        "exit_price": trade["exit_price"],

        "trade_return_percent": trade_return,

        "equity": new_equity,

        "exit_reason": trade["exit_reason"],
    }

    rows.append(row)

    return equity_curve


# ============================================================
# BULK TRADE UPDATE
# ============================================================

def add_completed_trades_to_equity(
    equity_curve,
    trades,
):
    """
    Add multiple completed trades in chronological order.
    """

    if not trades:
        return equity_curve

    sorted_trades = sorted(
        trades,
        key=lambda trade: trade["exit_timestamp"],
    )

    for trade in sorted_trades:
        add_completed_trade_to_equity(
            equity_curve,
            trade,
        )

    return equity_curve


# ============================================================
# DATAFRAME CONVERSION
# ============================================================

EQUITY_COLUMNS = [
    "method_id",
    "symbol",

    "entry_timestamp",
    "exit_timestamp",

    "entry_price",
    "exit_price",

    "trade_return_percent",

    "equity",

    "exit_reason",
]


def equity_curve_to_dataframe(equity_curve):
    """
    Convert one in-memory equity curve to a DataFrame.
    """

    rows = equity_curve["rows"]

    if not rows:
        return pd.DataFrame(
            columns=EQUITY_COLUMNS
        )

    dataframe = pd.DataFrame(rows)

    for column in EQUITY_COLUMNS:
        if column not in dataframe.columns:
            dataframe[column] = np.nan

    dataframe = dataframe[EQUITY_COLUMNS]

    return dataframe


# ============================================================
# SHARED EQUITY DATA
# ============================================================

def equity_curves_to_dataframe(equity_curves):
    """
    Convert all method equity curves into one shared DataFrame.

    equity_curves:
        {
            method_id: equity_curve,
            method_id: equity_curve,
            ...
        }
    """

    frames = []

    for equity_curve in equity_curves.values():

        dataframe = equity_curve_to_dataframe(
            equity_curve
        )

        if not dataframe.empty:
            frames.append(dataframe)

    if not frames:
        return pd.DataFrame(
            columns=EQUITY_COLUMNS
        )

    return pd.concat(
        frames,
        ignore_index=True,
    )


# ============================================================
# LOAD PERSISTED EQUITY CURVES
# ============================================================

def dataframe_to_equity_curves(dataframe):
    """
    Reconstruct the in-memory equity-curve dictionary
    from the shared persisted DataFrame.
    """

    equity_curves = {}

    if dataframe.empty:
        return equity_curves

    dataframe = dataframe.sort_values(
        ["method_id", "exit_timestamp"]
    )

    for method_id, group in dataframe.groupby(
        "method_id",
        sort=False,
    ):

        group = group.reset_index(drop=True)

        symbol = group.iloc[0]["symbol"]

        rows = group.to_dict(
            orient="records"
        )

        equity_curves[method_id] = {
            "method_id": method_id,
            "symbol": symbol,
            "rows": rows,
        }

    return equity_curves


# ============================================================
# LATEST EQUITY STATE
# ============================================================

def get_latest_equity_state(
    equity_data,
    method_id,
):
    """
    Return the latest completed equity row for a method.

    No current timestamp is required.

    The latest row simply means the row with the latest
    completed trade timestamp for that method.
    """

    if equity_data is None:
        return None

    if isinstance(equity_data, dict):

        equity_curve = equity_data.get(method_id)

        if equity_curve is None:
            return None

        rows = equity_curve.get("rows", [])

        if not rows:
            return None

        return rows[-1]

    if isinstance(equity_data, pd.DataFrame):

        if equity_data.empty:
            return None

        method_rows = equity_data[
            equity_data["method_id"] == method_id
        ]

        if method_rows.empty:
            return None

        method_rows = method_rows.sort_values(
            "exit_timestamp"
        )

        return method_rows.iloc[-1].to_dict()

    raise TypeError(
        "equity_data must be a dictionary or DataFrame"
    )


# ============================================================
# LATEST EQUITY
# ============================================================

def get_latest_equity(
    equity_data,
    method_id,
):
    """
    Return the latest equity value.

    A method with no completed trades has equity = 1.0.
    """

    latest = get_latest_equity_state(
        equity_data,
        method_id,
    )

    if latest is None:
        return 1.0

    return float(latest["equity"])


# ============================================================
# EQUITY ROC
# ============================================================

def calculate_equity_roc(
    current_equity,
    previous_equity,
):
    """
    Calculate percentage change between two equity values.
    """

    if previous_equity <= 0:
        return np.nan

    return (
        (current_equity - previous_equity)
        / previous_equity
    ) * 100.0


def get_equity_roc(
    equity_data,
    method_id,
):
    """
    Calculate the latest equity ROC for a method.

    Uses the two most recent completed trades.

    A method with fewer than two completed trades
    has no calculable ROC.
    """

    if isinstance(equity_data, dict):

        equity_curve = equity_data.get(method_id)

        if equity_curve is None:
            return np.nan

        rows = equity_curve.get("rows", [])

        if len(rows) < 2:
            return np.nan

        previous_equity = float(
            rows[-2]["equity"]
        )

        current_equity = float(
            rows[-1]["equity"]
        )

    elif isinstance(equity_data, pd.DataFrame):

        if equity_data.empty:
            return np.nan

        rows = equity_data[
            equity_data["method_id"] == method_id
        ].sort_values("exit_timestamp")

        if len(rows) < 2:
            return np.nan

        previous_equity = float(
            rows.iloc[-2]["equity"]
        )

        current_equity = float(
            rows.iloc[-1]["equity"]
        )

    else:
        raise TypeError(
            "equity_data must be a dictionary or DataFrame"
        )

    return calculate_equity_roc(
        current_equity,
        previous_equity,
    )


# ============================================================
# EQUITY STATISTICS
# ============================================================

def get_equity_statistics(
    equity_curve,
):
    """
    Calculate basic statistics for one method's equity curve.
    """

    rows = equity_curve["rows"]

    if not rows:
        return {
            "method_id": equity_curve["method_id"],
            "symbol": equity_curve["symbol"],

            "start_equity": 1.0,
            "final_equity": 1.0,

            "total_return_percent": 0.0,

            "trade_count": 0,
            "win_count": 0,
            "loss_count": 0,

            "win_rate": np.nan,
            "average_trade_return_percent": np.nan,
        }

    equity_values = np.asarray(
        [row["equity"] for row in rows],
        dtype=np.float64,
    )

    trade_returns = np.asarray(
        [
            row["trade_return_percent"]
            for row in rows
        ],
        dtype=np.float64,
    )

    win_count = int(
        np.sum(trade_returns > 0)
    )

    loss_count = int(
        np.sum(trade_returns <= 0)
    )

    trade_count = len(trade_returns)

    win_rate = (
        win_count / trade_count * 100.0
        if trade_count > 0
        else np.nan
    )

    return {
        "method_id": equity_curve["method_id"],
        "symbol": equity_curve["symbol"],

        "start_equity": 1.0,
        "final_equity": float(equity_values[-1]),

        "total_return_percent": (
            equity_values[-1] - 1.0
        ) * 100.0,

        "trade_count": trade_count,
        "win_count": win_count,
        "loss_count": loss_count,

        "win_rate": win_rate,

        "average_trade_return_percent": float(
            np.mean(trade_returns)
        ),
    }


# ============================================================
# UPDATE ONE METHOD
# ============================================================

def update_equity_curve(
    equity_curve,
    completed_trade,
):
    """
    Main function for updating one method's equity curve.

    This should be called whenever the simulator completes
    a trade.
    """

    if completed_trade is None:
        return equity_curve

    return add_completed_trade_to_equity(
        equity_curve,
        completed_trade,
    )