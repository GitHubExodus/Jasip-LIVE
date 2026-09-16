# ==========================================
# Script: methods.py
# Type: Script / method-definition module
# Purpose: Centralizes method schema, identity, and parameter generation.
# ==========================================

import itertools
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Any

import config


# ==========================================
# Start: Part 5.1 Method Definition
# ==========================================
@dataclass(frozen=True)
class Method:
    """
    Standardized dataclass representing a unique strategy trading instance.
    
    Fields:
      symbol: Ticker symbol (e.g., 'AAPL')
      timeframe: Execution timeframe ('5m', '30m', '1d')
      strategy: Strategy name identifier ('ema_cross')
      ema_pair: Tuple of (fast_period, slow_period)
      sl_multiplier: Stop loss multiplier factor
      risk_reward: Risk-to-reward ratio for take profit calculation
    """
    symbol: str
    timeframe: str
    strategy: str
    ema_pair: Tuple[int, int]
    sl_multiplier: float
    risk_reward: float
    _contribution: float = field(default=0.0, repr=False, compare=False)

    @property
    def fast_period(self) -> int:
        return self.ema_pair[0]

    @property
    def slow_period(self) -> int:
        return self.ema_pair[1]

    @property
    def identity(self) -> str:
        """Alias property for seamless method ID resolution across live.py and morning.py."""
        return get_method_id(self)

    @property
    def contribution(self) -> float:
        """Property returning the method's allocation contribution weight."""
        return self._contribution
# ==========================================
# End: Part 5.1 Method Definition
# ==========================================


# ==========================================
# Start: Part 5.2 Method Identity
# ==========================================
def get_method_id(method: Method) -> str:
    """
    Generates a unique, deterministic, and standardized string identifier for a Method.
    
    Format: {SYMBOL}_{TIMEFRAME}_{STRATEGY}_{FAST}x{SLOW}_SL{SL_MULT}_RR{RR}
    Example: AAPL_5m_ema_cross_3x5_SL2_RR5
    """
    # Clean multiplier and RR representation to prevent floating point formatting discrepancies
    sl_str = f"{method.sl_multiplier:g}"
    rr_str = f"{method.risk_reward:g}"
    
    return (
        f"{method.symbol}_{method.timeframe}_{method.strategy}_"
        f"{method.fast_period}x{method.slow_period}_"
        f"SL{sl_str}_RR{rr_str}"
    )
# ==========================================
# End: Part 5.2 Method Identity
# ==========================================


# ==========================================
# Start: Part 5.3 Method Combination Generator
# ==========================================
def generate_methods(
    symbol: str,
    timeframes: Optional[List[str]] = None,
    strategies: Optional[Tuple[str, ...]] = None,
    sl_multipliers: Optional[List[float]] = None,
    risk_rewards: Optional[List[float]] = None
) -> List[Method]:
    """
    Generates all valid strategy Method permutations for a given stock symbol
    using explicit parameters or falling back to master configurations from config.py.
    """
    tfs = timeframes if timeframes is not None else config.TIMEFRAMES
    strats = strategies if strategies is not None else getattr(config, "STRATEGIES", ("ema_cross",))
    sls = sl_multipliers if sl_multipliers is not None else config.SL_MULTIPLIERS
    rrs = risk_rewards if risk_rewards is not None else config.RISK_REWARD_VALUES
    ema_pairs = getattr(config, "EMA_PAIRS", [(3, 5), (5, 10), (8, 21)])

    methods: List[Method] = []
    
    for tf, strat, ema_pair, sl_mult, rr in itertools.product(
        tfs,
        strats,
        ema_pairs,
        sls,
        rrs
    ):
        method = Method(
            symbol=symbol,
            timeframe=tf,
            strategy=strat,
            ema_pair=ema_pair,
            sl_multiplier=float(sl_mult),
            risk_reward=float(rr)
        )
        methods.append(method)
        
    return methods


def generate_all_universe_methods(symbols: List[str]) -> List[Method]:
    """
    Generates method permutations across the entire active universe of symbols.
    """
    all_methods: List[Method] = []
    for symbol in symbols:
        all_methods.extend(generate_methods(symbol))
    return all_methods
# ==========================================
# End: Part 5.3 Method Combination Generator
# ==========================================


# ==========================================
# Start: Part 5.4 Method Interface
# ==========================================
class MethodManager:
    """
    Public access interface for creating, indexing, and generating Method objects.
    """
    
    @staticmethod
    def create_method(
        symbol: str,
        timeframe: str,
        ema_pair: Tuple[int, int],
        sl_multiplier: float,
        risk_reward: float,
        strategy: str = "ema_cross"
    ) -> Method:
        """Constructs a single Method instance."""
        return Method(
            symbol=symbol,
            timeframe=timeframe,
            strategy=strategy,
            ema_pair=ema_pair,
            sl_multiplier=float(sl_multiplier),
            risk_reward=float(risk_reward)
        )

    @staticmethod
    def get_id(method: Method) -> str:
        """Retrieves the standard string identifier for a given Method."""
        return get_method_id(method)

    @staticmethod
    def get_methods_for_symbol(symbol: str, **kwargs: Any) -> List[Method]:
        """Returns all strategy method permutations for a target symbol."""
        return generate_methods(symbol, **kwargs)

    @staticmethod
    def get_methods_for_universe(symbols: List[str]) -> List[Method]:
        """Returns all strategy method permutations across multiple symbols."""
        return generate_all_universe_methods(symbols)
# ==========================================
# End: Part 5.4 Method Interface
# ==========================================