from dataclasses import dataclass
from datetime import datetime

import numpy as np

from old.config import (
    DEFAULT_POSITION_FRACTION,
    MIN_ORDER_NOTIONAL,
)

from old.strategies import (
    STRATEGY_FUNCTIONS,
    EXIT_FUNCTIONS,
)

from old.storage import (
    load_trades,
    save_trades,
    append_equity,
    load_state,
    save_state,
)


# ============================================================
# METHOD
# ============================================================

@dataclass(
    frozen=True
)
class Method:

    symbol: str
    timeframe: str
    strategy: str
    stop_loss_percent: float
    risk_reward: float

    @property
    def identifier(self):

        return (
            f"{self.symbol}_"
            f"{self.timeframe}_"
            f"{self.strategy}_"
            f"sl_{self.stop_loss_percent}_"
            f"rr_{self.risk_reward}"
        )


# ============================================================
# OPEN TRADE
# ============================================================

@dataclass
class OpenTrade:

    method_id: str

    symbol: str
    timeframe: str
    strategy: str

    stop_loss_percent: float
    risk_reward: float

    start_time: str
    start_price: float

    stop_loss_price: float
    take_profit_price: float

    quantity: float


# ============================================================
# RR PRICES
# ============================================================

def calculate_rr_prices(
    entry_price,
    stop_loss_percent,
    risk_reward,
):

    sl_distance = (
        entry_price
        * stop_loss_percent
        / 100.0
    )

    stop_price = (
        entry_price
        - sl_distance
    )

    tp_distance = (
        sl_distance
        * risk_reward
    )

    take_profit_price = (
        entry_price
        + tp_distance
    )

    return (
        stop_price,
        take_profit_price,
    )


# ============================================================
# TRADE MANAGER
# ============================================================

class TradeManager:

    def __init__(
        self,
        alpaca_client,
        methods,
    ):

        self.alpaca = alpaca_client
        self.methods = methods

        self.open_trades = {}

        self._load_states()


    # ========================================================
    # STATE
    # ========================================================

    def _load_states(
        self
    ):

        symbols = set(
            method.symbol
            for method in self.methods
        )

        for symbol in symbols:

            state = load_state(
                symbol
            )

            for item in state.get(
                "open_trades",
                [],
            ):

                trade = OpenTrade(
                    **item
                )

                self.open_trades[
                    trade.method_id
                ] = trade


    def _save_symbol_state(
        self,
        symbol,
    ):

        trades = []

        for trade in (
            self.open_trades.values()
        ):

            if trade.symbol == symbol:

                trades.append(
                    trade.__dict__
                )

        save_state(
            symbol,
            {
                "open_trades": trades
            }
        )


    # ========================================================
    # CHECK WHETHER METHOD IS OPEN
    # ========================================================

    def has_open_trade(
        self,
        method,
    ):

        return (
            method.identifier
            in self.open_trades
        )


    # ========================================================
    # ENTER
    # ========================================================

    def enter(
        self,
        method,
        price,
        timestamp,
        account_equity,
    ):

        if self.has_open_trade(
            method
        ):
            return

        notional = (
            account_equity
            * DEFAULT_POSITION_FRACTION
        )

        if notional < MIN_ORDER_NOTIONAL:
            return

        quantity = (
            notional
            / price
        )

        (
            stop_price,
            take_profit_price,
        ) = calculate_rr_prices(
            price,
            method.stop_loss_percent,
            method.risk_reward,
        )

        # ----------------------------------------------------
        # Submit paper order
        # ----------------------------------------------------

        self.alpaca.submit_market_buy(
            method.symbol,
            quantity,
        )

        trade = OpenTrade(
            method_id=method.identifier,

            symbol=method.symbol,
            timeframe=method.timeframe,
            strategy=method.strategy,

            stop_loss_percent=(
                method.stop_loss_percent
            ),

            risk_reward=(
                method.risk_reward
            ),

            start_time=str(
                timestamp
            ),

            start_price=float(
                price
            ),

            stop_loss_price=float(
                stop_price
            ),

            take_profit_price=float(
                take_profit_price
            ),

            quantity=float(
                quantity
            ),
        )

        self.open_trades[
            method.identifier
        ] = trade

        self._save_symbol_state(
            method.symbol
        )

        print(
            f"ENTRY | "
            f"{method.identifier} | "
            f"price={price:.4f} | "
            f"SL={stop_price:.4f} | "
            f"TP={take_profit_price:.4f}"
        )


    # ========================================================
    # CHECK OPEN TRADE
    # ========================================================

    def check_trade(
        self,
        trade,
        candle,
    ):

        high = float(
            candle["high"]
        )

        low = float(
            candle["low"]
        )

        # ----------------------------------------------------
        # SL gets priority if both happen in same candle.
        # ----------------------------------------------------

        if low <= trade.stop_loss_price:

            self.close_trade(
                trade,
                trade.stop_loss_price,
                candle["timestamp"],
                "stop_loss",
            )

            return

        if high >= trade.take_profit_price:

            self.close_trade(
                trade,
                trade.take_profit_price,
                candle["timestamp"],
                "take_profit",
            )

            return


    # ========================================================
    # STRATEGY EXIT
    # ========================================================

    def check_strategy_exit(
        self,
        method,
        df,
    ):

        if method.identifier not in self.open_trades:
            return

        exit_function = EXIT_FUNCTIONS.get(
            method.strategy
        )

        if exit_function is None:
            return

        if exit_function(df):

            trade = self.open_trades[
                method.identifier
            ]

            price = float(
                df["close"].iloc[-1]
            )

            timestamp = (
                df["timestamp"].iloc[-1]
            )

            self.close_trade(
                trade,
                price,
                timestamp,
                "strategy_exit",
            )


    # ========================================================
    # CLOSE
    # ========================================================

    def close_trade(
        self,
        trade,
        exit_price,
        timestamp,
        reason,
    ):

        # ----------------------------------------------------
        # Sell paper position
        # ----------------------------------------------------

        self.alpaca.submit_market_sell(
            trade.symbol,
            trade.quantity,
        )

        entry_value = (
            trade.start_price
            * trade.quantity
        )

        exit_value = (
            exit_price
            * trade.quantity
        )

        profit = (
            exit_value
            - entry_value
        )

        return_percent = (
            (
                exit_price
                / trade.start_price
            )
            - 1.0
        ) * 100.0

        # ----------------------------------------------------
        # Save completed trade
        # ----------------------------------------------------

        trades = load_trades(
            trade.symbol
        )

        new_trade = {
            "symbol": trade.symbol,
            "timeframe": trade.timeframe,
            "strategy": trade.strategy,
            "stop_loss_percent": (
                trade.stop_loss_percent
            ),
            "risk_reward": (
                trade.risk_reward
            ),
            "start_time": trade.start_time,
            "start_price": trade.start_price,
            "stop_loss_price": (
                trade.stop_loss_price
            ),
            "take_profit_price": (
                trade.take_profit_price
            ),
            "end_time": str(timestamp),
            "end_price": float(exit_price),
            "profit": float(profit),
            "return_percent": float(
                return_percent
            ),
            "exit_reason": reason,
        }

        import pandas as pd

        trades = pd.concat(
            [
                trades,
                pd.DataFrame(
                    [new_trade]
                ),
            ],
            ignore_index=True,
        )

        save_trades(
            trade.symbol,
            trades,
        )

        # ----------------------------------------------------
        # IMPORTANT:
        #
        # Equity changes ONLY NOW.
        # ----------------------------------------------------

        new_equity = append_equity(
            trade.symbol,
            timestamp,
            profit,
        )

        print(
            f"EXIT | "
            f"{trade.method_id} | "
            f"{reason} | "
            f"entry={trade.start_price:.4f} | "
            f"exit={exit_price:.4f} | "
            f"profit={profit:.2f} | "
            f"equity={new_equity:.2f}"
        )

        del self.open_trades[
            trade.method_id
        ]

        self._save_symbol_state(
            trade.symbol
        )


    # ========================================================
    # CHECK ALL OPEN TRADES FOR CANDLE
    # ========================================================

    def check_all_trades(
        self,
        symbol,
        candle,
    ):

        trades = [
            trade
            for trade
            in self.open_trades.values()
            if trade.symbol == symbol
        ]

        for trade in trades:

            self.check_trade(
                trade,
                candle,
            )


    # ========================================================
    # SIGNAL
    # ========================================================

    def process_signal(
        self,
        method,
        df,
        account_equity,
    ):

        if self.has_open_trade(
            method
        ):
            return

        strategy_function = (
            STRATEGY_FUNCTIONS[
                method.strategy
            ]
        )

        signal = strategy_function(
            df
        )

        if signal == 1:

            price = float(
                df["close"].iloc[-1]
            )

            timestamp = (
                df["timestamp"].iloc[-1]
            )

            self.enter(
                method,
                price,
                timestamp,
                account_equity,
            )