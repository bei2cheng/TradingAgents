"""Unit tests for quant_strategy.rating.rater — rating conclusion must match the backtest signal engine exactly."""
import pandas as pd
import pytest

from quant_strategy.rating.rater import rate
from quant_strategy.strategy.engine import generate_signals
from quant_strategy.strategy.schema import Condition, IndicatorRef, Rule, StrategySpec


def _df():
    dates = pd.date_range("2024-01-01", periods=6, freq="B")
    closes = pd.Series([10.0, 10.0, 10.0, 20.0, 20.0, 5.0], index=dates)
    return pd.DataFrame({
        "open": closes, "high": closes, "low": closes, "close": closes,
        "volume": pd.Series([100.0] * 6, index=dates),
    }, index=dates)


def _spec():
    entry = Rule.leaf(Condition(left=IndicatorRef(name="close"), comparator="gte", right=20.0))
    exit_rule = Rule.leaf(Condition(left=IndicatorRef(name="close"), comparator="lte", right=5.0))
    return StrategySpec(name="t", description="", mode="dsl", entry_rule=entry, exit_rule=exit_rule)


def test_rating_matches_engine_signal_for_every_date():
    df = _df()
    spec = _spec()
    signals = generate_signals(spec, df)

    for date in df.index:
        result = rate(spec, "X.SH", str(date.date()), df=df)
        assert result.rating == signals.loc[date]


def test_rating_includes_triggered_condition_description():
    df = _df()
    spec = _spec()
    result = rate(spec, "X.SH", str(df.index[3].date()), df=df)  # close=20 -> BUY

    assert result.rating == "BUY"
    assert result.triggered_entry is True
    assert "close" in result.entry_description


def test_rating_hold_has_no_triggered_condition():
    df = _df()
    spec = _spec()
    result = rate(spec, "X.SH", str(df.index[0].date()), df=df)  # close=10 -> HOLD

    assert result.rating == "HOLD"
    assert result.triggered_entry is False
    assert result.triggered_exit is False


def test_rating_raises_for_date_without_data():
    df = _df()
    spec = _spec()
    with pytest.raises(ValueError):
        rate(spec, "X.SH", "2030-01-01", df=df)
