# -*- coding: utf-8 -*-
"""A股历史日线行情获取（baostock），与 reports/analyze_stock.py 使用同一数据源；结果落盘缓存避免重复请求。"""
import os

import baostock as bs
import pandas as pd

from qmt_trading.stock_picker.universe import to_bs_code
from quant_strategy.config import DATA_CACHE_DIR

DAILY_FIELDS = "date,open,high,low,close,volume,amount,turn,pctChg"


def _cache_path(ticker: str, start_date: str, end_date: str) -> str:
    fname = f"{ticker}_{start_date}_{end_date}.csv".replace(".", "_", 1)
    return os.path.join(DATA_CACHE_DIR, fname)


def _fetch_daily_raw(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """假定已 bs.login()，向 baostock 请求单只股票日线数据。"""
    bs_code = to_bs_code(ticker)
    rs = bs.query_history_k_data_plus(
        bs_code, DAILY_FIELDS, start_date=start_date, end_date=end_date,
        frequency="d", adjustflag="2",
    )
    if rs.error_code != "0":
        raise RuntimeError(f"baostock 查询 {ticker} 失败：{rs.error_msg}")
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())

    columns = ["date", "open", "high", "low", "close", "volume", "amount", "turn", "pctChg"]
    df = pd.DataFrame(rows, columns=columns)
    if df.empty:
        raise RuntimeError(f"{ticker} 在 {start_date}~{end_date} 无行情数据")
    for col in columns[1:]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["date"])
    return df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)


def fetch_daily(ticker: str, start_date: str, end_date: str, use_cache: bool = True) -> pd.DataFrame:
    """获取单只A股日线前复权行情。

    ticker 形如 "600519.SH"；start_date/end_date 形如 "2024-01-01"。
    返回按日期升序的 DataFrame，index 为 date（Timestamp），列：open/high/low/close/volume/amount/turn/pctChg。
    """
    cache_path = _cache_path(ticker, start_date, end_date)
    if use_cache and os.path.isfile(cache_path):
        df = pd.read_csv(cache_path, parse_dates=["date"])
        return df.set_index("date").sort_index()

    bs.login()
    try:
        df = _fetch_daily_raw(ticker, start_date, end_date)
    finally:
        bs.logout()

    if use_cache:
        df.to_csv(cache_path, index=False)

    return df.set_index("date").sort_index()


def fetch_many(tickers: list, start_date: str, end_date: str, use_cache: bool = True) -> dict:
    """批量获取多只股票的日线数据，返回 {ticker: DataFrame}；单只失败不影响其他股票。"""
    result = {}
    to_fetch = []
    for ticker in tickers:
        cache_path = _cache_path(ticker, start_date, end_date)
        if use_cache and os.path.isfile(cache_path):
            df = pd.read_csv(cache_path, parse_dates=["date"])
            result[ticker] = df.set_index("date").sort_index()
        else:
            to_fetch.append(ticker)

    if to_fetch:
        bs.login()
        try:
            for ticker in to_fetch:
                try:
                    df = _fetch_daily_raw(ticker, start_date, end_date)
                    if use_cache:
                        df.to_csv(_cache_path(ticker, start_date, end_date), index=False)
                    result[ticker] = df.set_index("date").sort_index()
                except Exception as e:
                    print(f"[market_data] {ticker} 获取失败，跳过：{e}")
        finally:
            bs.logout()

    return result
