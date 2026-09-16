# methods.py

from dataclasses import dataclass

from old3.config import (
    EMA_PAIRS,
    STOP_LOSS_MULTIPLIERS,
    RISK_REWARD_RATIOS,
)


@dataclass(frozen=True)
class Method:
    symbol: str
    timeframe: str
    strategy: str
    fast: int
    slow: int
    stop_loss_multiplier: float
    risk_reward: float

    @property
    def id(self):
        return (
            f"{self.symbol}_"
            f"{self.timeframe}_"
            f"{self.strategy}_"
            f"{self.fast}_{self.slow}_"
            f"sl{self.stop_loss_multiplier}_"
            f"rr{self.risk_reward}"
        )


def create_methods(symbol, timeframe):
    methods = []

    for fast, slow in EMA_PAIRS:
        for sl in STOP_LOSS_MULTIPLIERS:
            for rr in RISK_REWARD_RATIOS:
                methods.append(
                    Method(
                        symbol=symbol,
                        timeframe=timeframe,
                        strategy="ema_cross",
                        fast=fast,
                        slow=slow,
                        stop_loss_multiplier=sl,
                        risk_reward=rr,
                    )
                )

    return methods


def create_all_methods(symbols, timeframes):
    methods = []

    for symbol in symbols:
        for timeframe in timeframes:
            methods.extend(
                create_methods(
                    symbol,
                    timeframe,
                )
            )

    return methods