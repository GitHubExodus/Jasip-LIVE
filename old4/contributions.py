"""
contributions.py

Converts the latest equity ROC values into contribution percentages,
identifies the tradeable top methods, and maintains global contribution history.
"""

from typing import Any, Dict, List, Tuple, Union, Optional
import pandas as pd

# Import from core system modules
import config
from methods import Method, get_method_id


# ==============================================================================
# ========= Start: Helper Utilities & Data Extraction ==========================
# ==============================================================================

def extract_equity_df(all_equity_data: Union[pd.DataFrame, Dict[str, Any]]) -> pd.DataFrame:
    """
    Normalizes inputs (whether a single DataFrame or a Dict of symbol -> EquityData/DataFrame)
    into a single combined Pandas DataFrame.
    """
    if isinstance(all_equity_data, pd.DataFrame):
        return all_equity_data.copy()

    dfs = []
    if isinstance(all_equity_data, dict):
        for symbol, data in all_equity_data.items():
            if isinstance(data, pd.DataFrame):
                dfs.append(data)
            elif hasattr(data, "df") and isinstance(data.df, pd.DataFrame):
                dfs.append(data.df)
            elif hasattr(data, "equity_df") and isinstance(data.equity_df, pd.DataFrame):
                dfs.append(data.equity_df)

    if dfs:
        return pd.concat(dfs, ignore_index=True)
    return pd.DataFrame(columns=["method_id", "exit_timestamp", "equity", "roc"])

# ==============================================================================
# ======= End: Helper Utilities & Data Extraction ==============================
# ==============================================================================


# ==============================================================================
# ========= Start: 7.1 Latest Equity State =====================================
# ==============================================================================

def get_latest_equity_state(equity_input: Union[pd.DataFrame, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Extracts the latest completed equity record and ROC state for every method.

    Responsibilities:
    - Find the latest equity record for each method based on exit_timestamp.
    - Use the latest equity-curve ROC.
    - Ignore open or incomplete trades.
    - Ensure every method present in the equity dataset is represented.
    """
    equity_df = extract_equity_df(equity_input)
    if equity_df.empty:
        return {}

    # Ensure chronological order by exit_timestamp
    sorted_df = equity_df.sort_values(by="exit_timestamp", ascending=True)

    # Group by method_id and extract the most recent row
    latest_rows = sorted_df.groupby("method_id", as_index=False).last()

    latest_states: Dict[str, Dict[str, Any]] = {}
    for _, row in latest_rows.iterrows():
        method_id = str(row["method_id"])
        latest_states[method_id] = {
            "equity": float(row["equity"]),
            "roc": float(row["roc"]),
            "exit_timestamp": pd.to_datetime(row["exit_timestamp"])
        }

    return latest_states

# ==============================================================================
# ======= End: 7.1 Latest Equity State =========================================
# ==============================================================================


# ==============================================================================
# ========= Start: 7.2 Positive ROC Calculation ===============================
# ==============================================================================

def calculate_positive_roc(
    latest_states: Dict[str, Dict[str, Any]]
) -> Tuple[Dict[str, float], float]:
    """
    Determines which ROC values contribute to allocation and calculates total positive ROC.
    """
    positive_rocs: Dict[str, float] = {}
    total_positive_roc: float = 0.0

    for method_id, state in latest_states.items():
        roc_val = state.get("roc", 0.0)
        if roc_val > 0.0:
            positive_rocs[method_id] = float(roc_val)
            total_positive_roc += float(roc_val)
        else:
            positive_rocs[method_id] = 0.0

    return positive_rocs, total_positive_roc

# ==============================================================================
# ======= End: 7.2 Positive ROC Calculation ===================================
# ==============================================================================


# ==============================================================================
# ========= Start: 7.3 Contribution Calculation ================================
# ==============================================================================

def calculate_contributions(
    equity_input_or_rocs: Union[pd.DataFrame, Dict[str, Any]],
    total_positive_roc: Optional[float] = None
) -> Dict[str, float]:
    """
    Converts positive ROC into normalized allocation percentages.

    Supports dual invocation:
    1. calculate_contributions(all_updated_equity_dict_or_df)
    2. calculate_contributions(positive_rocs_dict, total_positive_roc_float)
    """
    if total_positive_roc is None:
        latest_states = get_latest_equity_state(equity_input_or_rocs)
        positive_rocs, total_pos_roc = calculate_positive_roc(latest_states)
    else:
        positive_rocs = equity_input_or_rocs  # type: ignore
        total_pos_roc = total_positive_roc

    contributions: Dict[str, float] = {}

    if total_pos_roc <= 0.0:
        for method_id in positive_rocs:
            contributions[method_id] = 0.0
        return contributions

    for method_id, pos_roc in positive_rocs.items():
        if pos_roc > 0.0:
            contributions[method_id] = float(pos_roc) / total_pos_roc
        else:
            contributions[method_id] = 0.0

    return contributions

# ==============================================================================
# ======= End: 7.3 Contribution Calculation ====================================
# ==============================================================================


# ==============================================================================
# ========= Start: 7.4 Method Ranking =========================================
# ==============================================================================

def rank_methods(
    latest_states_or_contributions: Union[Dict[str, Dict[str, Any]], Dict[str, float]],
    contributions: Optional[Dict[str, float]] = None
) -> List[Dict[str, Any]]:
    """
    Orders methods according to their current contribution and ROC state.

    Supports dual invocation:
    1. rank_methods(latest_states, contributions)
    2. rank_methods(contributions_dict)
    """
    if contributions is None:
        contrib_map = latest_states_or_contributions  # type: ignore
        state_map = {m_id: {"roc": c, "exit_timestamp": pd.Timestamp.min} for m_id, c in contrib_map.items()}
    else:
        state_map = latest_states_or_contributions  # type: ignore
        contrib_map = contributions

    records = []
    for method_id, state in state_map.items():
        contrib = contrib_map.get(method_id, 0.0)
        roc = state.get("roc", 0.0)
        ts = state.get("exit_timestamp", pd.Timestamp.min)
        records.append({
            "method_id": method_id,
            "roc": float(roc),
            "contribution": float(contrib),
            "exit_timestamp": ts
        })

    def sort_key(item):
        ts = item["exit_timestamp"]
        ts_val = ts.value if isinstance(ts, pd.Timestamp) else 0
        return (-item["contribution"], -item["roc"], -ts_val, str(item["method_id"]))

    ranked_records = sorted(records, key=sort_key)

    # Assign 1-based ranks
    for index, rec in enumerate(ranked_records, start=1):
        rec["rank"] = index

    return ranked_records

# ==============================================================================
# ======= End: 7.4 Method Ranking ==============================================
# ==============================================================================


# ==============================================================================
# ========= Start: 7.5 Top-N Selection =======================================
# ==============================================================================

def select_top_methods(
    ranked_methods: List[Dict[str, Any]],
    all_methods_map: Optional[Union[Dict[str, Method], List[Method]]] = None,
    limit: Optional[int] = None,
    max_methods: Optional[int] = None
) -> List[Tuple[Method, float]]:
    """
    Identifies methods eligible for live trading based on positive ROC and rank limit.
    """
    max_limit = limit if limit is not None else (max_methods if max_methods is not None else getattr(config, "MAX_TRADE_METHODS", 20))

    method_lookup: Dict[str, Method] = {}
    if isinstance(all_methods_map, list):
        method_lookup = {get_method_id(m): m for m in all_methods_map}
    elif isinstance(all_methods_map, dict):
        method_lookup = all_methods_map

    eligible: List[Tuple[Method, float]] = []

    for record in ranked_methods:
        if len(eligible) >= max_limit:
            break

        contrib = record.get("contribution", 0.0)
        roc = record.get("roc", 0.0)

        # Only methods with positive ROC / contribution are eligible
        if contrib > 0.0 and roc > 0.0:
            method_id = record["method_id"]
            if method_lookup and method_id in method_lookup:
                eligible.append((method_lookup[method_id], contrib))
            elif not method_lookup:
                # If no object lookup provided, return stub record
                eligible.append((method_id, contrib))  # type: ignore

    return eligible

# ==============================================================================
# ======= End: 7.5 Top-N Selection ===========================================
# ==============================================================================


# ==============================================================================
# ========= Start: 7.6 Contribution History & Records =========================
# ==============================================================================

def update_contribution_history(
    existing_history_df: Optional[pd.DataFrame],
    contributions: Dict[str, float],
    snapshot_timestamp: pd.Timestamp
) -> pd.DataFrame:
    """
    Preserves and appends historical contribution snapshots over time.
    """
    new_rows = []
    for method_id, contrib in contributions.items():
        new_rows.append({
            "timestamp": snapshot_timestamp,
            "method_id": method_id,
            "contribution": float(contrib)
        })

    snapshot_df = pd.DataFrame(new_rows)

    if existing_history_df is None or existing_history_df.empty:
        return snapshot_df

    return pd.concat([existing_history_df, snapshot_df], ignore_index=True)


def build_contribution_record(
    existing_contributions: Optional[pd.DataFrame],
    current_contributions: Dict[str, float],
    timestamp: pd.Timestamp
) -> pd.DataFrame:
    """
    Alias wrapper matching external interface for snapshot creation.
    """
    return update_contribution_history(
        existing_history_df=existing_contributions,
        contributions=current_contributions,
        snapshot_timestamp=timestamp
    )

# ==============================================================================
# ======= End: 7.6 Contribution History & Records ==============================
# ==============================================================================


# ==============================================================================
# ========= Start: 7.7 Contribution Interface ==================================
# ==============================================================================

def process_contributions(
    equity_df: pd.DataFrame,
    all_methods: List[Method],
    existing_history_df: Optional[pd.DataFrame] = None,
    snapshot_timestamp: Optional[pd.Timestamp] = None
) -> Dict[str, Any]:
    """
    Public API coordinating all internal contribution calculation steps.
    """
    if snapshot_timestamp is None:
        snapshot_timestamp = pd.Timestamp.now(tz=config.TIMEZONE)

    all_methods_map: Dict[str, Method] = {
        get_method_id(m): m for m in all_methods
    }

    latest_states = get_latest_equity_state(equity_df)

    # Ensure all generated methods exist in latest_states (fill missing with default ROC)
    for m_id in all_methods_map:
        if m_id not in latest_states:
            latest_states[m_id] = {
                "equity": getattr(config, "STARTING_EQUITY", 10000.0),
                "roc": 0.0,
                "exit_timestamp": pd.Timestamp.min
            }

    positive_rocs, total_positive_roc = calculate_positive_roc(latest_states)
    contributions = calculate_contributions(positive_rocs, total_positive_roc)
    ranked_methods = rank_methods(latest_states, contributions)

    tradeable_methods = select_top_methods(
        ranked_methods=ranked_methods,
        all_methods_map=all_methods_map,
        limit=getattr(config, "MAX_TRADE_METHODS", 20)
    )

    updated_history_df = update_contribution_history(
        existing_history_df,
        contributions,
        snapshot_timestamp
    )

    return {
        "latest_states": latest_states,
        "contributions": contributions,
        "ranked_methods": ranked_methods,
        "tradeable_methods": tradeable_methods,
        "updated_history_df": updated_history_df
    }

# ==============================================================================
# ======= End: 7.7 Contribution Interface ======================================
# ==============================================================================