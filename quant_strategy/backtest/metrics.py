# -*- coding: utf-8 -*-
"""回测常见指标计算：总收益/年化收益/最大回撤/夏普/卡玛/胜率/盈亏比/基准超额收益。"""
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


@dataclass
class Metrics:
    total_return: float
    annualized_return: float
    max_drawdown: float
    sharpe_ratio: float
    calmar_ratio: float
    win_rate: float | None
    profit_loss_ratio: float | None
    num_round_trips: int
    num_trades: int
    benchmark_total_return: float | None = None
    alpha: float | None = None

    def to_dict(self) -> dict:
        return {
            "总收益率": f"{self.total_return:.2%}",
            "年化收益率": f"{self.annualized_return:.2%}",
            "最大回撤": f"{self.max_drawdown:.2%}",
            "夏普比率": f"{self.sharpe_ratio:.2f}",
            "卡玛比率": f"{self.calmar_ratio:.2f}" if math.isfinite(self.calmar_ratio) else "N/A",
            "胜率": f"{self.win_rate:.2%}" if self.win_rate is not None else "N/A",
            "盈亏比": f"{self.profit_loss_ratio:.2f}" if self.profit_loss_ratio is not None else "N/A",
            "平仓次数": self.num_round_trips,
            "总成交笔数": self.num_trades,
            "基准收益率": (
                f"{self.benchmark_total_return:.2%}" if self.benchmark_total_return is not None else "N/A"
            ),
            "超额收益(alpha)": f"{self.alpha:.2%}" if self.alpha is not None else "N/A",
        }


def max_drawdown(equity: pd.Series) -> float:
    running_max = equity.cummax()
    drawdown = equity / running_max - 1
    return float(drawdown.min())


def sharpe_ratio(daily_returns: pd.Series, risk_free: float = 0.0) -> float:
    excess = daily_returns - risk_free / TRADING_DAYS_PER_YEAR
    std = excess.std()
    if std == 0 or math.isnan(std):
        return 0.0
    return float(excess.mean() / std * math.sqrt(TRADING_DAYS_PER_YEAR))


def compute_metrics(result) -> Metrics:
    equity = result.equity_curve["equity"]
    if len(equity) < 2:
        raise ValueError("回测数据点不足，无法计算指标（至少需要2个交易日）")

    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1)
    num_days = len(equity)
    years = num_days / TRADING_DAYS_PER_YEAR
    annualized_return = float((1 + total_return) ** (1 / years) - 1) if years > 0 else 0.0

    daily_returns = equity.pct_change().dropna()
    mdd = max_drawdown(equity)
    sharpe = sharpe_ratio(daily_returns)
    calmar = annualized_return / abs(mdd) if mdd != 0 else float("inf")

    sell_trades = [t for t in result.trades if t.side == "SELL" and t.pnl is not None]
    wins = [t.pnl for t in sell_trades if t.pnl > 0]
    losses = [t.pnl for t in sell_trades if t.pnl <= 0]
    win_rate = len(wins) / len(sell_trades) if sell_trades else None
    profit_loss_ratio = (
        (np.mean(wins) / abs(np.mean(losses))) if wins and losses else None
    )

    benchmark_total_return = None
    alpha = None
    if result.benchmark_curve is not None and not result.benchmark_curve.empty:
        bench_close = result.benchmark_curve["close"]
        benchmark_total_return = float(bench_close.iloc[-1] / bench_close.iloc[0] - 1)
        alpha = total_return - benchmark_total_return

    return Metrics(
        total_return=total_return,
        annualized_return=annualized_return,
        max_drawdown=mdd,
        sharpe_ratio=sharpe,
        calmar_ratio=calmar,
        win_rate=win_rate,
        profit_loss_ratio=profit_loss_ratio,
        num_round_trips=len(sell_trades),
        num_trades=len(result.trades),
        benchmark_total_return=benchmark_total_return,
        alpha=alpha,
    )
