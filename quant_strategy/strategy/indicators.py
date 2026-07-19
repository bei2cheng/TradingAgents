# -*- coding: utf-8 -*-
"""技术指标计算：纯函数，输入/输出均为 pandas Series，不依赖网络。

df 约定：按日期升序排列，至少包含 open/high/low/close/volume 列。
"""
import pandas as pd

from qmt_trading.stock_picker.indicators import ma as _ma
from quant_strategy.strategy.schema import DslError, IndicatorRef

EPS = 1e-10


def ma(close: pd.Series, window: int) -> pd.Series:
    return _ma(close, window)


def ema(close: pd.Series, window: int) -> pd.Series:
    return close.ewm(span=window, adjust=False).mean()


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    dif = ema(close, fast) - ema(close, slow)
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = (dif - dea) * 2
    return dif, dea, hist


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(window).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(window).mean()
    return 100 - 100 / (1 + gain / (loss + EPS))


def bollinger(close: pd.Series, window: int = 20, num_std: float = 2.0):
    mid = close.rolling(window).mean()
    std = close.rolling(window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, mid, lower


def volume_ratio(volume: pd.Series, short: int = 5, long: int = 20) -> pd.Series:
    return volume.rolling(short).mean() / (volume.rolling(long).mean() + EPS)


def highest(series: pd.Series, window: int) -> pd.Series:
    """过去 window 根K线（不含当根）的最高值，用于突破判断。"""
    return series.shift(1).rolling(window).max()


def lowest(series: pd.Series, window: int) -> pd.Series:
    return series.shift(1).rolling(window).min()


_FIELD_COLUMNS = {"close": "close", "open": "open", "high": "high", "low": "low", "volume": "volume"}


def resolve_indicator(df: pd.DataFrame, ref: IndicatorRef) -> pd.Series:
    """把 IndicatorRef 解析成对齐 df.index 的 Series。"""
    name = ref.name
    p = ref.params

    if name in _FIELD_COLUMNS:
        return df[_FIELD_COLUMNS[name]]

    if name == "ma":
        return ma(df["close"], int(p.get("window", 20)))
    if name == "ema":
        return ema(df["close"], int(p.get("window", 20)))
    if name in ("macd_dif", "macd_dea", "macd_hist"):
        dif, dea, hist = macd(
            df["close"], int(p.get("fast", 12)), int(p.get("slow", 26)), int(p.get("signal", 9))
        )
        return {"macd_dif": dif, "macd_dea": dea, "macd_hist": hist}[name]
    if name == "rsi":
        return rsi(df["close"], int(p.get("window", 14)))
    if name in ("boll_upper", "boll_mid", "boll_lower"):
        upper, mid, lower = bollinger(df["close"], int(p.get("window", 20)), float(p.get("num_std", 2.0)))
        return {"boll_upper": upper, "boll_mid": mid, "boll_lower": lower}[name]
    if name == "volume_ratio":
        return volume_ratio(df["volume"], int(p.get("short", 5)), int(p.get("long", 20)))
    if name == "highest":
        field_name = p.get("field", "close")
        return highest(df[_FIELD_COLUMNS.get(field_name, "close")], int(p.get("window", 20)))
    if name == "lowest":
        field_name = p.get("field", "close")
        return lowest(df[_FIELD_COLUMNS.get(field_name, "close")], int(p.get("window", 20)))

    raise DslError(f"无法解析指标：{name}")
