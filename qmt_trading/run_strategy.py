# -*- coding: utf-8 -*-
"""QMT 策略执行 CLI。

用法：
  python -m qmt_trading.run_strategy status --mode sim
  python -m qmt_trading.run_strategy plan --mode sim [--date 20260704]
  python -m qmt_trading.run_strategy execute --mode sim [--date 20260704] [--yes]

live（实盘）模式额外要求 --i-understand-real-money，且下单前必须交互输入 "CONFIRM"。
运行前请先启动国金证券QMT交易端并登录对应账号（sim=模拟盘 / live=实盘）。
"""
import argparse
import datetime
import json
import logging
import os
import sys

from qmt_trading.config import load_config
from qmt_trading.position_sizer import build_order_plans, format_order_plans
from qmt_trading.qmt_gateway import QmtGateway
from qmt_trading.report_parser import load_decisions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("qmt_trading.run_strategy")

TRADING_WINDOWS = [((9, 30), (11, 30)), ((13, 0), (15, 0))]


def _in_trading_hours(now=None) -> bool:
    now = now or datetime.datetime.now()
    if now.weekday() >= 5:
        return False
    t = (now.hour, now.minute)
    return any(start <= t <= end for start, end in TRADING_WINDOWS)


def _connect(config, mode):
    gateway = QmtGateway(config.userdata_path(mode), config.account_id(mode), config.account_type)
    gateway.connect(config.site_packages_path)
    return gateway


def cmd_status(args, config):
    gateway = _connect(config, args.mode)
    try:
        asset = gateway.get_asset()
        positions = gateway.get_positions()
        orders = gateway.query_orders()
        print(f"\n=== 账户资产（{args.mode}）===")
        for k, v in asset.items():
            print(f"  {k}: {v:,.2f}")
        print(f"\n=== 持仓（{len(positions)}）===")
        for ticker, p in positions.items():
            print(f"  {ticker}: 持仓 {p.volume} 可用 {p.can_use_volume} 市值 {p.market_value:,.2f}")
        print(f"\n=== 当日委托（{len(orders)}）===")
        for o in orders:
            print(f"  {o.stock_code} {o.order_status} 委托{o.order_volume} 已成{o.traded_volume}")
    finally:
        gateway.disconnect()


def _build_plan(args, config):
    tickers = list(config.stock_whitelist)
    decisions = load_decisions(tickers, config, date=args.date)

    gateway = _connect(config, args.mode)
    try:
        asset = gateway.get_asset()
        positions = gateway.get_positions()
        latest_prices = gateway.get_latest_price(tickers)
    finally:
        gateway.disconnect()

    plans = build_order_plans(
        decisions=decisions,
        total_asset=asset["total_asset"],
        cash=asset["cash"],
        positions=positions,
        latest_prices=latest_prices,
        config=config,
    )
    return decisions, asset, plans


def cmd_plan(args, config):
    _decisions, asset, plans = _build_plan(args, config)
    summary = format_order_plans(plans)
    print(f"\n账户总资产: {asset['total_asset']:,.2f}  可用现金: {asset['cash']:,.2f}\n")
    print(summary)

    date_tag = args.date or datetime.date.today().strftime("%Y%m%d")
    out_path = os.path.join(config.reports_base, f"qmt_orders_{date_tag}_{args.mode}.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# QMT 委托预览（{args.mode}）\n\n生成时间：{datetime.datetime.now()}\n\n")
        f.write(f"账户总资产: {asset['total_asset']:,.2f}  可用现金: {asset['cash']:,.2f}\n\n")
        f.write(summary + "\n")
    print(f"\n预览已保存: {out_path}")
    return plans


def cmd_execute(args, config):
    if args.mode == "live" and not args.i_understand_real_money:
        print("live 模式下单需要显式传入 --i-understand-real-money，已中止。")
        sys.exit(1)

    if not _in_trading_hours():
        if args.mode == "sim" and args.force_outside_hours:
            logger.warning("当前非交易时间，因 --force-outside-hours 继续执行（仅限 sim 联调）")
        else:
            print("当前非A股交易时间（09:30-11:30 / 13:00-15:00），已中止下单。")
            sys.exit(1)

    _decisions, asset, plans = _build_plan(args, config)
    summary = format_order_plans(plans)
    print(f"\n账户总资产: {asset['total_asset']:,.2f}  可用现金: {asset['cash']:,.2f}\n")
    print(summary)

    if not plans:
        print("无可执行委托单，退出。")
        return

    if not args.yes:
        prompt = "yes" if args.mode == "sim" else "CONFIRM"
        answer = input(f'\n确认按以上计划下单？请输入 "{prompt}" 继续：')
        if answer.strip() != prompt:
            print("未确认，已取消下单。")
            return

    gateway = _connect(config, args.mode)
    date_tag = args.date or datetime.date.today().strftime("%Y%m%d")
    log_path = os.path.join(config.reports_base, f"qmt_orders_log_{date_tag}.jsonl")
    try:
        with open(log_path, "a", encoding="utf-8") as logf:
            for plan in plans:
                record = {
                    "time": datetime.datetime.now().isoformat(),
                    "mode": args.mode,
                    "ticker": plan.ticker,
                    "side": plan.side,
                    "shares": plan.shares,
                    "limit_price": plan.limit_price,
                    "reason": plan.reason,
                }
                try:
                    order_id = gateway.place_order(
                        plan.ticker, plan.side, plan.shares, plan.limit_price
                    )
                    record["order_id"] = order_id
                    record["status"] = "submitted"
                    print(
                        f"  [下单成功] {plan.ticker} {plan.side} {plan.shares}股 "
                        f"@ {plan.limit_price} order_id={order_id}"
                    )
                except Exception as e:
                    record["status"] = "failed"
                    record["error"] = str(e)
                    print(f"  [下单失败] {plan.ticker} {plan.side} {plan.shares}股: {e}")
                logf.write(json.dumps(record, ensure_ascii=False) + "\n")
    finally:
        gateway.disconnect()
    print(f"\n下单日志已记录: {log_path}")


def main():
    parser = argparse.ArgumentParser(description="QMT 自动交易执行程序")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--mode", choices=["sim", "live"], default="sim", help="sim=模拟盘 live=实盘")
    common.add_argument(
        "--date", default=None, help="分析报告日期 YYYYMMDD，默认取每只股票最新报告"
    )

    sub.add_parser("status", parents=[common], help="查询账户资产/持仓/委托（只读）")
    sub.add_parser("plan", parents=[common], help="生成委托预览，不下单")
    p_execute = sub.add_parser("execute", parents=[common], help="生成委托并真实下单")
    p_execute.add_argument("--yes", action="store_true", help="跳过交互确认")
    p_execute.add_argument(
        "--force-outside-hours",
        action="store_true",
        help="仅sim模式：允许非交易时间下单，用于联调",
    )
    p_execute.add_argument(
        "--i-understand-real-money",
        action="store_true",
        help="live模式必需：确认知悉这是真实资金下单",
    )

    args = parser.parse_args()
    config = load_config()

    if args.command == "status":
        cmd_status(args, config)
    elif args.command == "plan":
        cmd_plan(args, config)
    elif args.command == "execute":
        cmd_execute(args, config)


if __name__ == "__main__":
    main()
