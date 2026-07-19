"""Unit tests for quant_strategy.strategy.indicators — pure indicator math on synthetic OHLCV data."""
import pandas as pd

from quant_strategy.strategy import indicators as ind
from quant_strategy.strategy.schema import IndicatorRef


def _df():
    close = pd.Series([10.0, 11.0, 12.0, 11.0, 10.0, 9.0, 10.0, 11.0, 12.0, 13.0])
    return pd.DataFrame({
        "open": close, "high": close + 1, "low": close - 1, "close": close,
        "volume": pd.Series([100.0] * 10),
    })


def test_ma_matches_manual_rolling_mean():
    close = _df()["close"]
    result = ind.ma(close, 3)
    assert result.iloc[2] == close.iloc[0:3].mean()


def test_macd_returns_three_series_same_length():
    close = _df()["close"]
    dif, dea, hist = ind.macd(close, fast=2, slow=4, signal=2)
    assert len(dif) == len(dea) == len(hist) == len(close)


def test_rsi_is_bounded_0_100():
    close = _df()["close"]
    result = ind.rsi(close, window=3).dropna()
    assert (result >= 0).all() and (result <= 100).all()


def test_bollinger_upper_above_mid_above_lower():
    close = _df()["close"]
    upper, mid, lower = ind.bollinger(close, window=3)
    valid = upper.notna() & mid.notna() & lower.notna()
    assert (upper[valid] >= mid[valid]).all()
    assert (mid[valid] >= lower[valid]).all()


def test_highest_excludes_current_bar():
    close = pd.Series([1.0, 2.0, 3.0, 100.0, 4.0])
    result = ind.highest(close, window=3)
    # 第4根K线（index 3, value 100.0）不应把自己算进过去3根的最高值
    assert result.iloc[3] == 3.0


def test_resolve_indicator_field_passthrough():
    df = _df()
    result = ind.resolve_indicator(df, IndicatorRef(name="close"))
    assert (result == df["close"]).all()


def test_resolve_indicator_ma_with_params():
    df = _df()
    result = ind.resolve_indicator(df, IndicatorRef(name="ma", params={"window": 3}))
    assert result.iloc[2] == df["close"].iloc[0:3].mean()
