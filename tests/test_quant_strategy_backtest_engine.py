"""Unit tests for quant_strategy.backtest.engine — synthetic OHLCV, no network/xtquant dependency."""
import pandas as pd
import pytest

from quant_strategy.backtest.engine import run_backtest
from quant_strategy.backtest.portfolio import Portfolio
from quant_strategy.config import BacktestDefaults
from quant_strategy.strategy.schema import Condition, IndicatorRef, Rule, StrategySpec


@pytest.fixture(autouse=True)
def _no_network_benchmark(monkeypatch):
    """回测结束时会尝试拉基准指数，测试环境无网络，直接让它抛错触发引擎里的 try/except 兜底。"""
    import quant_strategy.data.market_data as market_data

    def _boom(*args, **kwargs):
        raise RuntimeError("no network in tests")

    monkeypatch.setattr(market_data, "fetch_many", _boom)


def _close_gte_rule(threshold):
    return Rule.leaf(Condition(left=IndicatorRef(name="close"), comparator="gte", right=threshold))


def _close_lte_rule(threshold):
    return Rule.leaf(Condition(left=IndicatorRef(name="close"), comparator="lte", right=threshold))


def _synthetic_df(closes, dates=None):
    if dates is None:
        dates = pd.date_range("2024-01-01", periods=len(closes), freq="B")
    closes = pd.Series(closes, index=dates)
    return pd.DataFrame({
        "open": closes, "high": closes * 1.001, "low": closes * 0.999,
        "close": closes, "volume": pd.Series([1000.0] * len(closes), index=dates),
    }, index=dates)


def _no_slippage_no_fee_defaults():
    return BacktestDefaults(
        initial_cash=1_000_000.0, commission_rate=0.0, min_commission=0.0,
        stamp_tax_rate=0.0, slippage_pct=0.0, position_pct_per_trade=1.0,
    )


def test_buy_executes_when_entry_condition_met():
    df = _synthetic_df([100.0, 100.0, 100.0, 100.0, 100.0])
    spec = StrategySpec(name="t", description="", mode="dsl", entry_rule=_close_gte_rule(100.0))

    result = run_backtest(spec, ["X.SH"], "2024-01-01", "2024-12-31",
                           price_data={"X.SH": df}, defaults=_no_slippage_no_fee_defaults())

    buys = [t for t in result.trades if t.side == "BUY"]
    assert len(buys) == 1
    assert buys[0].shares % 100 == 0  # 整手取整


def test_shares_are_rounded_to_lot_size():
    # 目标市值 / 单价 不是100的整数倍，验证向下取整到整手
    df = _synthetic_df([33.0] * 5)
    spec = StrategySpec(name="t", description="", mode="dsl", entry_rule=_close_gte_rule(33.0))

    result = run_backtest(spec, ["X.SH"], "2024-01-01", "2024-12-31",
                           price_data={"X.SH": df}, defaults=_no_slippage_no_fee_defaults())

    buy = [t for t in result.trades if t.side == "BUY"][0]
    assert buy.shares % 100 == 0


def test_limit_up_blocks_same_day_buy():
    # day index: 0,1 平稳；day2 相对day1涨停(+10%以上)，理论买点恰好落在涨停当天 -> 不应成交
    closes = [100.0, 100.0, 111.0, 105.0, 105.0]
    df = _synthetic_df(closes)
    spec = StrategySpec(name="t", description="", mode="dsl", entry_rule=_close_gte_rule(111.0))

    result = run_backtest(spec, ["X.SH"], "2024-01-01", "2024-12-31",
                           price_data={"X.SH": df}, defaults=_no_slippage_no_fee_defaults())

    assert len(result.trades) == 0


def test_limit_down_blocks_same_day_sell():
    # 先买入建仓，之后模拟一个跌停日（相对前一日收盘 -10%以上）触发卖出信号，当天应被阻止
    dates = pd.date_range("2024-01-01", periods=5, freq="B")
    closes = [100.0, 100.0, 100.0, 89.0, 89.0]
    df = _synthetic_df(closes, dates=dates)
    entry = Rule.leaf(Condition(left=IndicatorRef(name="close"), comparator="gte", right=99.0))
    exit_rule = _close_lte_rule(89.0)
    spec = StrategySpec(name="t", description="", mode="dsl", entry_rule=entry, exit_rule=exit_rule)

    result = run_backtest(spec, ["X.SH"], "2024-01-01", "2024-12-31",
                           price_data={"X.SH": df}, defaults=_no_slippage_no_fee_defaults())

    limit_day = str(dates[3].date())
    sells_on_limit_day = [t for t in result.trades if t.side == "SELL" and t.date == limit_day]
    assert sells_on_limit_day == []  # 跌停当天(-11%)卖出信号应被阻止，无法成交


def test_full_exit_realizes_pnl_and_frees_position():
    closes = [100.0, 100.0, 100.0, 120.0, 120.0]
    df = _synthetic_df(closes)
    entry = Rule.leaf(Condition(left=IndicatorRef(name="close"), comparator="lte", right=100.0))
    exit_rule = Rule.leaf(Condition(left=IndicatorRef(name="close"), comparator="gte", right=120.0))
    spec = StrategySpec(name="t", description="", mode="dsl", entry_rule=entry, exit_rule=exit_rule)

    result = run_backtest(spec, ["X.SH"], "2024-01-01", "2024-12-31",
                           price_data={"X.SH": df}, defaults=_no_slippage_no_fee_defaults())

    sells = [t for t in result.trades if t.side == "SELL"]
    assert len(sells) == 1
    assert sells[0].pnl > 0  # 100 买入涨到 120 卖出，应为正收益


def test_portfolio_t_plus_1_sellable_tracking():
    portfolio = Portfolio(cash=100_000.0)
    pos = portfolio.get_position("X.SH")
    pos.shares = 100
    pos.sellable = 0  # 当日买入，尚不可卖
    assert pos.sellable == 0

    portfolio.roll_day_start()  # 进入下一交易日
    assert portfolio.get_position("X.SH").sellable == 100
