# -*- coding: utf-8 -*-
"""全市场A股扫描：找出当前（或指定日期）满足某策略目标评级（默认BUY）的股票。

复用既有基础设施，不重复造轮子：
- 股票池：qmt_trading.stock_picker.universe.get_universe()（沪深主板+创业板，剔除科创板/北交所/ST/停牌）
- 行情：quant_strategy.data.market_data.fetch_many()（批量拉取+本地缓存+单只失败跳过）
- 单股评级：quant_strategy.rating.rater.rate()（与回测同一套信号引擎，结论保证一致）
"""
import datetime
import os
import time

import pandas as pd

from qmt_trading.stock_picker.universe import get_universe, to_bs_code, to_ticker
from quant_strategy.config import STRATEGIES_DIR
from quant_strategy.data.market_data import fetch_many
from quant_strategy.rating.rater import DEFAULT_LOOKBACK_DAYS, rate
from quant_strategy.strategy.schema import StrategySpec

PROGRESS_EVERY = 200


def _build_universe(codes: list = None) -> list:
    if codes:
        return [{"code": to_bs_code(t), "name": ""} for t in codes]

    import baostock as bs

    bs.login()
    try:
        return get_universe()
    finally:
        bs.logout()


def screen_market(
    spec: StrategySpec,
    date: str = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    codes: list = None,
    limit: int = None,
    target_rating: str = "BUY",
) -> tuple:
    """遍历股票池，找出当前（或 date 这一天）评级等于 target_rating 的股票。

    date 不传时，对每只股票各自用其最新一根K线所在日期评级（应对不同股票历史长度/停牌差异更稳健）；
    传了 date 时，每只股票的行情先截断到 <= date，再用截断后最后一根K线的日期评级。

    返回 (matches, stats)；matches 每项是 rate() 的 RatingResult.to_dict()，并附加 ticker/name 字段。
    """
    scan_date = date or datetime.date.today().strftime("%Y-%m-%d")
    start_date = (pd.Timestamp(scan_date) - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    universe = _build_universe(codes)
    if limit:
        universe = universe[:limit]

    tickers = [to_ticker(u["code"]) for u in universe]
    name_by_ticker = {to_ticker(u["code"]): u["name"] for u in universe}

    started = time.time()
    data = fetch_many(tickers, start_date, scan_date)

    matches = []
    skipped = 0
    for i, ticker in enumerate(tickers, 1):
        df = data.get(ticker)
        if df is None or df.empty:
            skipped += 1
            continue

        eval_df = df.loc[:pd.Timestamp(scan_date)] if date else df
        if eval_df.empty:
            skipped += 1
            continue
        eval_date = str(eval_df.index[-1].date())

        try:
            result = rate(spec, ticker, date=eval_date, df=eval_df, lookback_days=lookback_days)
        except ValueError:
            skipped += 1
            continue

        if result.rating == target_rating:
            entry = result.to_dict()
            entry["股票代码"] = ticker
            entry["名称"] = name_by_ticker.get(ticker, "")
            matches.append(entry)

        if i % PROGRESS_EVERY == 0:
            elapsed = time.time() - started
            print(f"  进度 {i}/{len(tickers)}，命中 {len(matches)}，耗时 {elapsed:.0f}s")

    stats = {
        "total": len(tickers),
        "fetched": len(data),
        "skipped": skipped,
        "matched": len(matches),
        "elapsed": time.time() - started,
        "date": scan_date,
        "target_rating": target_rating,
    }
    return matches, stats


def generate_screen_report(matches: list, stats: dict, spec: StrategySpec) -> str:
    lines = [
        f"# 全市场扫描报告：{spec.name}（{stats['date']}，目标评级={stats['target_rating']}）",
        "",
        f"扫描范围：沪深主板+创业板（剔除科创板/北交所/ST/停牌）",
        f"总数 {stats['total']}，成功获取行情 {stats['fetched']}，跳过 {stats['skipped']}，"
        f"命中 {stats['matched']}，耗时 {stats['elapsed']:.0f}秒",
        "",
    ]
    if not matches:
        lines.append("（本次未筛出符合条件的股票）")
        return "\n".join(lines) + "\n"

    lines.append("| 代码 | 名称 | 评级 | 日期 | 收盘价 | 触发条件 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for m in matches:
        desc = m.get("买入条件") or m.get("卖出条件") or "-"
        lines.append(
            f"| {m['股票代码']} | {m['名称']} | {m['评级']} | {m['日期']} | {m['收盘价']:.2f} | {desc} |"
        )
    return "\n".join(lines) + "\n"


def default_screen_report_path(strategy_name: str, date: str) -> str:
    reports_dir = os.path.join(STRATEGIES_DIR, "reports")
    return os.path.join(reports_dir, f"screen_{strategy_name}_{date}.md")
