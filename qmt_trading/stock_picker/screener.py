# -*- coding: utf-8 -*-
"""周线选股 CLI。

用法：
  python -m qmt_trading.stock_picker.screener [--mode all|any] [--aggressive]
      [--limit N] [--codes 600519.SH,000001.SZ]

--mode all（默认）：4条策略条件必须同时满足才算命中（可能命中很少甚至为空）
--mode any：命中任意一条即算命中
--aggressive：策略2改用门槛更低的"突破前三周最高收盘/开盘价"判断（而非前四周最高价）
--limit：只扫描前N只（联调用）
--codes：指定股票代码（TICKER.SH/SZ格式），跳过全市场清单拉取（联调用）
"""
import argparse
import datetime
import os
import time

import baostock as bs

from qmt_trading.stock_picker.conditions import MIN_WEEKS, evaluate_all
from qmt_trading.stock_picker.indicators import ma
from qmt_trading.stock_picker.universe import get_universe, to_bs_code, to_ticker
from qmt_trading.stock_picker.weekly_data import fetch_weekly

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
HISTORY_YEARS = 3
PROGRESS_EVERY = 200


def _build_universe(codes: str = None):
    if codes:
        tickers = [t.strip() for t in codes.split(",") if t.strip()]
        return [{"code": to_bs_code(t), "name": ""} for t in tickers]
    return get_universe()


def _extract_summary(ticker: str, name: str, df, result: dict) -> dict:
    close = df["close"]
    ma5, ma20, ma60 = ma(close, 5), ma(close, 20), ma(close, 60)
    return {
        "ticker": ticker,
        "name": name,
        "matched": result["matched"],
        "date": str(df["date"].iloc[-1].date()),
        "close": round(float(close.iloc[-1]), 2),
        "ma5": round(float(ma5.iloc[-1]), 2),
        "ma20": round(float(ma20.iloc[-1]), 2),
        "ma60": round(float(ma60.iloc[-1]), 2),
        "volume": int(df["volume"].iloc[-1]),
    }


def run_screen(mode: str = "all", aggressive: bool = False, limit: int = None, codes: str = None):
    end_date = datetime.date.today().strftime("%Y-%m-%d")
    start_date = (datetime.date.today() - datetime.timedelta(days=365 * HISTORY_YEARS)).strftime("%Y-%m-%d")

    matches = []
    scanned = 0
    skipped_short_history = 0
    failed = 0

    started = time.time()
    bs.login()
    try:
        universe = _build_universe(codes)  # get_universe() 需要已登录的 baostock 会话
        if limit:
            universe = universe[:limit]

        for i, stock in enumerate(universe, 1):
            code, name = stock["code"], stock["name"]
            ticker = to_ticker(code)
            try:
                df = fetch_weekly(code, start_date, end_date)
                if len(df) < MIN_WEEKS:
                    skipped_short_history += 1
                    continue
                scanned += 1
                result = evaluate_all(df, aggressive=aggressive, mode=mode)
                if result["overall_hit"]:
                    matches.append(_extract_summary(ticker, name, df, result))
            except Exception as e:
                failed += 1
                print(f"  [跳过] {ticker} 获取/计算失败: {e}")

            if i % PROGRESS_EVERY == 0:
                elapsed = time.time() - started
                print(f"  进度 {i}/{len(universe)}，已扫描 {scanned}，命中 {len(matches)}，耗时 {elapsed:.0f}s")
    finally:
        bs.logout()

    elapsed = time.time() - started
    stats = {
        "total": len(universe),
        "scanned": scanned,
        "skipped_short_history": skipped_short_history,
        "failed": failed,
        "matched": len(matches),
        "elapsed": elapsed,
        "mode": mode,
        "aggressive": aggressive,
    }
    return matches, stats


def _format_report(matches, stats) -> str:
    date_tag = datetime.date.today().strftime("%Y-%m-%d")
    lines = [
        f"# 周线选股报告（{date_tag}）",
        "",
        f"组合模式：{stats['mode']}（{'4条全部满足' if stats['mode'] == 'all' else '满足任意一条'}）"
        f"{' + 激进突破' if stats['aggressive'] else ''}",
        f"扫描范围：沪深主板+创业板（剔除科创板/北交所/ST/次新股）",
        f"总数 {stats['total']}，实际参与判断 {stats['scanned']}"
        f"（历史不足跳过 {stats['skipped_short_history']}，获取失败 {stats['failed']}），"
        f"命中 {stats['matched']}，耗时 {stats['elapsed']:.0f}秒",
        "",
    ]
    if not matches:
        lines.append("（本次未筛出符合条件的股票）")
        return "\n".join(lines)

    lines.append("| 代码 | 名称 | 命中策略 | 最新周 | 收盘 | MA5 | MA20 | MA60 | 成交量 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for m in matches:
        matched_str = ",".join(str(x) for x in m["matched"])
        lines.append(
            f"| {m['ticker']} | {m['name']} | {matched_str} | {m['date']} | "
            f"{m['close']} | {m['ma5']} | {m['ma20']} | {m['ma60']} | {m['volume']} |"
        )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="周线选股扫描")
    parser.add_argument("--mode", choices=["all", "any"], default="all", help="all=4条全满足 any=满足任意一条")
    parser.add_argument("--aggressive", action="store_true", help="策略2叠加激进突破条件")
    parser.add_argument("--limit", type=int, default=None, help="只扫描前N只（联调用）")
    parser.add_argument("--codes", default=None, help="指定股票代码，逗号分隔，如 600519.SH,000001.SZ")
    args = parser.parse_args()

    matches, stats = run_screen(
        mode=args.mode, aggressive=args.aggressive, limit=args.limit, codes=args.codes
    )

    report = _format_report(matches, stats)
    print("\n" + report)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    date_tag = datetime.date.today().strftime("%Y%m%d")
    out_path = os.path.join(OUTPUT_DIR, f"selected_{date_tag}.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print(f"\n报告已保存: {out_path}")


if __name__ == "__main__":
    main()
