# -*- coding: utf-8 -*-
"""持仓/现金/权益曲线记录，纯数据结构，不依赖 QMT。"""
from dataclasses import dataclass, field


@dataclass
class Position:
    shares: int = 0
    sellable: int = 0  # T+1：当日买入的股份要到下一交易日才计入 sellable
    cost_basis: float = 0.0  # 当前持仓的累计成本（含手续费），用于计算平仓盈亏


@dataclass
class Trade:
    date: str
    ticker: str
    side: str  # "BUY" / "SELL"
    shares: int
    price: float
    commission: float
    stamp_tax: float = 0.0
    pnl: float | None = None  # 仅 SELL 且完全平仓时填写


@dataclass
class Portfolio:
    cash: float
    positions: dict = field(default_factory=dict)  # ticker -> Position
    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)  # [(date, equity), ...]

    def roll_day_start(self) -> None:
        """每个新交易日开盘前调用：前一交易日及更早买入的份额变为可卖。"""
        for pos in self.positions.values():
            pos.sellable = pos.shares

    def get_position(self, ticker: str) -> Position:
        return self.positions.setdefault(ticker, Position())

    def market_value(self, prices: dict) -> float:
        return sum(pos.shares * prices.get(ticker, 0.0) for ticker, pos in self.positions.items())

    def equity(self, prices: dict) -> float:
        return self.cash + self.market_value(prices)

    def record_equity(self, date, prices: dict) -> None:
        self.equity_curve.append((date, self.equity(prices)))
