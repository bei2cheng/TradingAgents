# -*- coding: utf-8 -*-
"""周线选股基础指标计算：纯函数，不依赖网络/baostock，方便单测。"""
import pandas as pd

EPS = 1e-6


def ma(series: pd.Series, n: int) -> pd.Series:
    """简单移动平均。"""
    return series.rolling(window=n, min_periods=n).mean()


def body_ratio(open_: float, close: float, high: float, low: float) -> float:
    """K线实体占振幅的比例，越小越接近十字星/短实体。"""
    rng = max(high - low, EPS)
    return abs(close - open_) / rng
