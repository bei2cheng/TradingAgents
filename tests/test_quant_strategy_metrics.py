"""Unit tests for quant_strategy.backtest.metrics — computed from known equity curves."""
import math

import pandas as pd
import pytest

from quant_strategy.backtest.engine import BacktestResult
from quant_strategy.backtest.metrics import compute_metrics, max_drawdown


def _result(equity_values, benchmark_values=None, trades=None):
    dates = pd.date_range("2024-01-01", periods=len(equity_values), freq="B")
    equity_curve = pd.DataFrame({"equity": equity_values}, index=dates)
    benchmark_curve = None
    if benchmark_values is not None:
        benchmark_curve = pd.DataFrame({"close": benchmark_values}, index=dates)
    return BacktestResult(
        ticker_codes=["X.SH"], equity_curve=equity_curve, trades=trades or [],
        initial_cash=equity_values[0], final_cash=equity_values[-1], final_equity=equity_values[-1],
        benchmark_curve=benchmark_curve,
    )


def test_total_return_matches_simple_ratio():
    result = _result([100.0, 105.0, 110.0])
    metrics = compute_metrics(result)
    assert metrics.total_return == pytest.approx(0.10)


def test_max_drawdown_detects_the_dip():
    equity = pd.Series([100.0, 120.0, 90.0, 130.0])
    mdd = max_drawdown(equity)
    # 峰值120 -> 谷底90，回撤 = 90/120 - 1 = -25%
    assert mdd == pytest.approx(-0.25)


def test_alpha_is_strategy_minus_benchmark_return():
    result = _result([100.0, 110.0, 120.0], benchmark_values=[100.0, 105.0, 108.0])
    metrics = compute_metrics(result)
    assert metrics.benchmark_total_return == pytest.approx(0.08)
    assert metrics.alpha == pytest.approx(metrics.total_return - 0.08)


def test_win_rate_and_profit_loss_ratio_from_sell_trades():
    from quant_strategy.backtest.portfolio import Trade

    trades = [
        Trade(date="2024-01-02", ticker="X.SH", side="SELL", shares=100, price=11.0, commission=1.0, pnl=100.0),
        Trade(date="2024-01-03", ticker="X.SH", side="SELL", shares=100, price=9.0, commission=1.0, pnl=-50.0),
    ]
    result = _result([100.0, 200.0, 250.0], trades=trades)
    metrics = compute_metrics(result)
    assert metrics.win_rate == pytest.approx(0.5)
    assert metrics.profit_loss_ratio == pytest.approx(100.0 / 50.0)


def test_too_few_data_points_raises():
    result = _result([100.0])
    with pytest.raises(ValueError):
        compute_metrics(result)


def test_flat_equity_curve_has_zero_sharpe_and_return():
    result = _result([100.0] * 10)
    metrics = compute_metrics(result)
    assert metrics.total_return == 0.0
    assert metrics.sharpe_ratio == 0.0
    assert math.isinf(metrics.calmar_ratio)  # 无回撤时卡玛比率视为无穷
