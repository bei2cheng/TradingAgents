# -*- coding: utf-8 -*-
"""单只股票周线行情获取（baostock）。调用前需已 bs.login()。"""
import pandas as pd

import baostock as bs

WEEKLY_FIELDS = "date,open,high,low,close,volume,amount"


def fetch_weekly(bs_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """返回按日期升序的周线 DataFrame（前复权），列：date/open/high/low/close/volume/amount。

    baostock 会把当前未走完的这一周也聚合进最后一根K线，符合"最新"的选股诉求。
    """
    rs = bs.query_history_k_data_plus(
        bs_code,
        WEEKLY_FIELDS,
        start_date=start_date,
        end_date=end_date,
        frequency="w",
        adjustflag="2",  # 前复权
    )
    if rs.error_code != "0":
        return pd.DataFrame()

    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume", "amount"])
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["date"])
    df = df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
    return df
