# -*- coding: utf-8 -*-
"""全市场A股清单获取与过滤（沪深主板+创业板，剔除科创板/北交所/ST/停牌）。"""
import datetime

import baostock as bs


def _in_scope(code: str) -> bool:
    """code 形如 'sh.600000' / 'sz.300750'，只保留沪深主板+创业板，剔除科创板(688)/北交所/指数。"""
    market, _, digits = code.partition(".")
    if market == "sh":
        return digits.startswith("60")
    if market == "sz":
        return digits[:3] in ("000", "001", "002", "003", "300", "301")
    return False


def _is_st_or_delisted(name: str) -> bool:
    upper_name = (name or "").upper()
    return "ST" in upper_name or "退" in (name or "")


def to_ticker(bs_code: str) -> str:
    """'sh.600000' -> '600000.SH'"""
    market, _, digits = bs_code.partition(".")
    return f"{digits}.{market.upper()}"


def to_bs_code(ticker: str) -> str:
    """'600000.SH' -> 'sh.600000'"""
    digits, _, market = ticker.partition(".")
    return f"{market.lower()}.{digits}"


MAX_LOOKBACK_DAYS = 10  # query_all_stock 当天数据通常要等收盘后批处理才更新，向前多找几天兜底


def _query_all_stock_rows(day: str) -> list:
    rs = bs.query_all_stock(day=day)
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    return rows


def get_universe(day: str = None) -> list:
    """返回 [{"code": "sh.600000", "name": "..."}...]，已过滤板块/ST/停牌。

    需要在调用前后自行管理 bs.login()/bs.logout()（screener.py 里统一管理，避免每次调用重复登录）。

    baostock 的 query_all_stock 对"当天"的数据通常要收盘后批处理才会更新（当天盘中/未收盘查询会
    返回空），因此这里从指定日期起向前逐天回退，直到找到有数据的最近一天（周末/节假日也会返回空，
    一并跳过）。
    """
    day = day or datetime.date.today().strftime("%Y-%m-%d")
    cursor = datetime.datetime.strptime(day, "%Y-%m-%d").date()

    rows = []
    for _ in range(MAX_LOOKBACK_DAYS):
        rows = _query_all_stock_rows(cursor.strftime("%Y-%m-%d"))
        if rows:
            break
        cursor -= datetime.timedelta(days=1)
    else:
        raise RuntimeError(f"最近 {MAX_LOOKBACK_DAYS} 天内 baostock 均未返回股票清单数据，请检查网络/baostock 服务状态")

    universe = []
    for code, trade_status, name in rows:
        if trade_status != "1":
            continue
        if not _in_scope(code):
            continue
        if _is_st_or_delisted(name):
            continue
        universe.append({"code": code, "name": name})
    return universe
