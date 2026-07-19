# -*- coding: utf-8 -*-
"""事件驱动回测引擎：逐日推进，按策略信号模拟A股成交（T+1、整手、涨跌停不可成交、滑点、手续费）。"""
import math
from dataclasses import dataclass

import pandas as pd

from quant_strategy.backtest.portfolio import Portfolio, Trade
from quant_strategy.config import AShare, BacktestDefault
from quant_strategy.strategy.engine import BUY, SELL, generate_signals
from quant_strategy.strategy.schema import StrategySpec

LIMIT_EPS = 0.001  # 涨跌停判断容差


@dataclass
class BacktestResult:
    ticker_codes: list
    equity_curve: pd.DataFrame  # 列：date, equity
    trades: list
    initial_cash: float
    final_cash: float
    final_equity: float
    benchmark_curve: pd.DataFrame | None = None  # 列：date, close（已归一化为净值）


def _commission(notional: float, rate: float, min_commission: float) -> float:
    return max(notional * rate, min_commission)


def _is_limit_up(price: float, prev_close: float, limit_pct: float) -> bool:
    if prev_close is None or prev_close != prev_close or prev_close <= 0:  # NaN check
        return False
    return price >= prev_close * (1 + limit_pct - LIMIT_EPS)


def _is_limit_down(price: float, prev_close: float, limit_pct: float) -> bool:
    if prev_close is None or prev_close != prev_close or prev_close <= 0:
        return False
    return price <= prev_close * (1 - limit_pct + LIMIT_EPS)


def run_backtest(
    spec: StrategySpec,
    codes: list,
    start_date: str,
    end_date: str,
    initial_cash: float = None,
    rules=AShare,
    defaults=BacktestDefault,
    price_data: dict = None,
) -> BacktestResult:
    """对给定股票池、时间区间跑单一策略的回测。

    price_data: 可选，预先取好的 {ticker: DataFrame}（列含 open/high/low/close/volume，index为日期），
    不传则内部调用 data.market_data.fetch_many 拉取。
    """
    from quant_strategy.data.market_data import fetch_many

    initial_cash = initial_cash if initial_cash is not None else defaults.initial_cash
    data = price_data if price_data is not None else fetch_many(codes, start_date, end_date)
    codes = [c for c in codes if c in data and not data[c].empty]
    if not codes:
        raise RuntimeError("没有任何股票获取到有效行情数据，无法回测")

    signals = {ticker: generate_signals(spec, df) for ticker, df in data.items() if ticker in codes}
    prev_close = {ticker: df["close"].shift(1) for ticker, df in data.items() if ticker in codes}

    all_dates = sorted(set().union(*(df.index for df in data.values())))
    all_dates = [d for d in all_dates if pd.Timestamp(start_date) <= d <= pd.Timestamp(end_date)]

    alloc_pct = defaults.position_pct_per_trade if defaults.position_pct_per_trade > 0 else 1.0 / len(codes)

    portfolio = Portfolio(cash=initial_cash)
    last_price = {}

    for date in all_dates:
        portfolio.roll_day_start()

        for ticker in codes:
            df = data[ticker]
            if date not in df.index:
                continue

            close = float(df.loc[date, "close"])
            last_price[ticker] = close
            signal = signals[ticker].loc[date]
            p_close = prev_close[ticker].loc[date]
            pos = portfolio.get_position(ticker)

            if signal == BUY and pos.shares == 0:
                if _is_limit_up(close, p_close, rules.price_limit_pct):
                    continue
                fill_price = close * (1 + defaults.slippage_pct)
                target_value = portfolio.equity(last_price) * alloc_pct
                affordable = math.floor(portfolio.cash / fill_price / rules.lot_size) * rules.lot_size
                shares = min(
                    math.floor(target_value / fill_price / rules.lot_size) * rules.lot_size,
                    affordable,
                )
                if shares <= 0:
                    continue
                notional = shares * fill_price
                commission = _commission(notional, defaults.commission_rate, defaults.min_commission)
                portfolio.cash -= notional + commission
                pos.shares += shares
                pos.cost_basis += notional + commission
                portfolio.trades.append(
                    Trade(date=str(date.date()), ticker=ticker, side="BUY",
                          shares=shares, price=fill_price, commission=commission)
                )

            elif signal == SELL and pos.sellable > 0:
                if _is_limit_down(close, p_close, rules.price_limit_pct):
                    continue
                shares = pos.sellable
                fill_price = close * (1 - defaults.slippage_pct)
                notional = shares * fill_price
                commission = _commission(notional, defaults.commission_rate, defaults.min_commission)
                stamp_tax = notional * defaults.stamp_tax_rate
                proceeds = notional - commission - stamp_tax
                portfolio.cash += proceeds
                pnl = proceeds - pos.cost_basis * (shares / pos.shares) if pos.shares else None
                pos.shares -= shares
                pos.sellable -= shares
                pos.cost_basis = 0.0 if pos.shares == 0 else pos.cost_basis * (1 - shares / (pos.shares + shares))
                portfolio.trades.append(
                    Trade(date=str(date.date()), ticker=ticker, side="SELL",
                          shares=shares, price=fill_price, commission=commission,
                          stamp_tax=stamp_tax, pnl=pnl)
                )

        portfolio.record_equity(date, last_price)

    equity_df = pd.DataFrame(portfolio.equity_curve, columns=["date", "equity"]).set_index("date")

    benchmark_curve = None
    try:
        bench_df = fetch_many([defaults.benchmark_code], start_date, end_date).get(defaults.benchmark_code)
        if bench_df is not None and not bench_df.empty:
            bench_close = bench_df["close"].reindex(equity_df.index).ffill().bfill()
            benchmark_curve = pd.DataFrame({"close": bench_close / bench_close.iloc[0] * initial_cash})
    except Exception as e:
        print(f"[backtest] 基准指数获取失败，跳过超额收益计算：{e}")

    return BacktestResult(
        ticker_codes=codes,
        equity_curve=equity_df,
        trades=portfolio.trades,
        initial_cash=initial_cash,
        final_cash=portfolio.cash,
        final_equity=equity_df["equity"].iloc[-1] if not equity_df.empty else initial_cash,
        benchmark_curve=benchmark_curve,
    )
