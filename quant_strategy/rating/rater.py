# -*- coding: utf-8 -*-
"""给定策略 + 股票代码 + 日期，复用回测同一套信号引擎跑出该日期截面的 BUY/SELL/HOLD 评级，附带可解释的触发条件。"""
from dataclasses import dataclass

import pandas as pd

from quant_strategy.data.market_data import fetch_daily
from quant_strategy.strategy.engine import evaluate_rule, generate_signals
from quant_strategy.strategy.schema import StrategySpec

DEFAULT_LOOKBACK_DAYS = 400  # 日历天数，保证MA60/布林带等长周期指标有足够历史数据


@dataclass
class RatingResult:
    ticker: str
    date: str
    rating: str  # BUY / SELL / HOLD
    close_price: float
    triggered_entry: bool = False
    triggered_exit: bool = False
    entry_description: str | None = None
    exit_description: str | None = None

    def to_dict(self) -> dict:
        return {
            "股票代码": self.ticker,
            "日期": self.date,
            "评级": self.rating,
            "收盘价": self.close_price,
            "买入条件触发": self.triggered_entry,
            "买入条件": self.entry_description,
            "卖出条件触发": self.triggered_exit,
            "卖出条件": self.exit_description,
        }


def _lookback_start(date: str, lookback_days: int) -> str:
    return (pd.Timestamp(date) - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")


def rate(
    spec: StrategySpec,
    ticker: str,
    date: str,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    df: pd.DataFrame = None,
) -> RatingResult:
    """在 date 这一天的截面上跑策略信号，返回 BUY/SELL/HOLD 评级及（DSL模式下）触发条件说明。"""
    target_ts = pd.Timestamp(date)
    data = df if df is not None else fetch_daily(ticker, _lookback_start(date, lookback_days), date)
    data = data.loc[:target_ts]

    if data.empty or target_ts not in data.index:
        raise ValueError(f"{ticker} 在 {date} 无行情数据（非交易日或数据缺失）")

    signals = generate_signals(spec, data)
    rating = signals.loc[target_ts]

    result = RatingResult(
        ticker=ticker,
        date=date,
        rating=rating,
        close_price=float(data.loc[target_ts, "close"]),
    )

    if spec.mode == "dsl":
        if spec.entry_rule is not None:
            entry_series = evaluate_rule(data, spec.entry_rule)
            result.triggered_entry = bool(entry_series.loc[target_ts])
            if result.triggered_entry:
                result.entry_description = spec.entry_rule.describe()
        if spec.exit_rule is not None:
            exit_series = evaluate_rule(data, spec.exit_rule)
            result.triggered_exit = bool(exit_series.loc[target_ts])
            if result.triggered_exit:
                result.exit_description = spec.exit_rule.describe()

    return result
