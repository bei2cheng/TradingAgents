# -*- coding: utf-8 -*-
"""quant_strategy 统一 CLI 入口。

用法：
  python -m quant_strategy.cli define --text "MA5上穿MA20买入，下穿卖出" --name ma_cross
  python -m quant_strategy.cli define --file strategy.md --name ma_cross
  python -m quant_strategy.cli backtest --strategy ma_cross --codes 600519.SH,000001.SZ --start 2024-01-01 --end 2026-07-01
  python -m quant_strategy.cli rate --strategy ma_cross --code 600519.SH --date 2026-07-18
  python -m quant_strategy.cli screen --strategy bot_vol_rally
  python -m quant_strategy.cli trade plan --strategy ma_cross --codes 600519.SH,000001.SZ --mode sim
  python -m quant_strategy.cli trade execute --strategy ma_cross --codes 600519.SH,000001.SZ --mode sim
"""
import argparse
import os
import sys

from quant_strategy.config import STRATEGIES_DIR


def _strategy_path(name: str) -> str:
    return os.path.join(STRATEGIES_DIR, f"{name}.json")


def _load_strategy(name: str):
    from quant_strategy.strategy.schema import StrategySpec

    path = _strategy_path(name)
    if not os.path.isfile(path):
        print(f"未找到策略 {name}（期望路径：{path}），请先用 define 子命令生成。")
        sys.exit(1)
    return StrategySpec.load(path)


_STRATEGY_TEXT_FILE_EXTS = (".txt", ".md", ".markdown")


def _read_strategy_text_file(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext not in _STRATEGY_TEXT_FILE_EXTS:
        print(f"不支持的策略描述文件格式：{ext}（仅支持 {'/'.join(_STRATEGY_TEXT_FILE_EXTS)}）")
        sys.exit(1)
    if not os.path.isfile(path):
        print(f"未找到策略描述文件：{path}")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        text = f.read().strip()
    if not text:
        print(f"策略描述文件为空：{path}")
        sys.exit(1)
    return text


def cmd_define(args):
    from quant_strategy.strategy.compiler import DslUnsupportedError, compile_text_to_strategy

    text = _read_strategy_text_file(args.file) if args.file else args.text

    try:
        spec = compile_text_to_strategy(text, args.name)
    except DslUnsupportedError as e:
        print(f"无法把该描述转换为可执行策略：{e}")
        sys.exit(1)

    path = _strategy_path(args.name)
    spec.save(path)
    print(f"策略已生成并保存：{path}")
    print(f"模式：{spec.mode}")
    if spec.mode == "dsl":
        if spec.entry_rule:
            print(f"买入条件：{spec.entry_rule.describe()}")
        if spec.exit_rule:
            print(f"卖出条件：{spec.exit_rule.describe()}")
    else:
        print("模式为 code（DSL 无法表达，已用 LLM 生成并通过安全校验的代码）")


def cmd_backtest(args):
    from quant_strategy.backtest.engine import run_backtest
    from quant_strategy.backtest.report import default_report_path, generate_report

    spec = _load_strategy(args.strategy)
    codes = [c.strip() for c in args.codes.split(",") if c.strip()]

    result = run_backtest(spec, codes, args.start, args.end)
    out_path = args.output or default_report_path(args.strategy, args.start, args.end)
    report = generate_report(result, spec, args.start, args.end, output_path=out_path)
    print(report)
    print(f"\n报告已保存：{out_path}")


def cmd_rate(args):
    from quant_strategy.rating.rater import rate

    spec = _load_strategy(args.strategy)
    result = rate(spec, args.code, args.date)
    for k, v in result.to_dict().items():
        print(f"{k}: {v}")


def cmd_screen(args):
    from quant_strategy.rating.screener import default_screen_report_path, generate_screen_report, screen_market

    spec = _load_strategy(args.strategy)
    codes = [c.strip() for c in args.codes.split(",") if c.strip()] if args.codes else None

    kwargs = {"date": args.date, "codes": codes, "limit": args.limit, "target_rating": args.rating}
    if args.lookback_days is not None:
        kwargs["lookback_days"] = args.lookback_days

    matches, stats = screen_market(spec, **kwargs)

    report = generate_screen_report(matches, stats, spec)
    print(report)

    out_path = args.output or default_screen_report_path(args.strategy, stats["date"])
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n报告已保存：{out_path}")


def cmd_trade_plan(args, execute: bool):
    from quant_strategy.live.bridge import build_plan_for_date
    from qmt_trading.position_sizer import format_order_plans
    from qmt_trading.run_strategy import _in_trading_hours

    spec = _load_strategy(args.strategy)
    codes = [c.strip() for c in args.codes.split(",") if c.strip()]

    ratings, decisions, asset, plans = build_plan_for_date(
        spec, codes, args.date, mode=args.mode, buy_label=args.buy_label
    )

    print(f"\n=== 评级结果（{args.date}）===")
    for r in ratings:
        print(f"  {r.ticker}: {r.rating}  收盘价={r.close_price:.2f}")

    print(f"\n账户总资产: {asset['total_asset']:,.2f}  可用现金: {asset['cash']:,.2f}\n")
    summary = format_order_plans(plans)
    print(summary)

    if not execute:
        return plans

    if args.mode == "live" and not args.i_understand_real_money:
        print("live 模式下单需要显式传入 --i-understand-real-money，已中止。")
        sys.exit(1)

    if not _in_trading_hours() and not (args.mode == "sim" and args.force_outside_hours):
        print("当前非A股交易时间（09:30-11:30 / 13:00-15:00），已中止下单。")
        sys.exit(1)

    if not plans:
        print("无可执行委托单，退出。")
        return plans

    if not args.yes:
        prompt = "yes" if args.mode == "sim" else "CONFIRM"
        answer = input(f'\n确认按以上计划下单？请输入 "{prompt}" 继续：')
        if answer.strip() != prompt:
            print("未确认，已取消下单。")
            return plans

    from qmt_trading.config import load_config
    from qmt_trading.qmt_gateway import QmtGateway

    qmt_config = load_config()
    gateway = QmtGateway(
        qmt_config.userdata_path(args.mode), qmt_config.account_id(args.mode), qmt_config.account_type
    )
    gateway.connect(qmt_config.site_packages_path)
    try:
        for plan in plans:
            try:
                order_id = gateway.place_order(plan.ticker, plan.side, plan.shares, plan.limit_price)
                print(f"  [下单成功] {plan.ticker} {plan.side} {plan.shares}股 @ {plan.limit_price} order_id={order_id}")
            except Exception as e:
                print(f"  [下单失败] {plan.ticker} {plan.side} {plan.shares}股: {e}")
    finally:
        gateway.disconnect()
    return plans


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="quant_strategy：策略文字转代码 / A股回测 / 评级 / 对接国金证券交易")
    sub = parser.add_subparsers(dest="command", required=True)

    p_define = sub.add_parser("define", help="把策略文字描述转换成可执行策略并保存")
    p_define_input = p_define.add_mutually_exclusive_group(required=True)
    p_define_input.add_argument("--text", help="策略的中文文字描述")
    p_define_input.add_argument("--file", help="策略描述文件路径（.txt/.md/.markdown），与 --text 二选一")
    p_define.add_argument("--name", required=True, help="保存的策略名（对应 strategies/{name}.json）")

    p_backtest = sub.add_parser("backtest", help="对指定股票池和时间区间跑回测，输出报告")
    p_backtest.add_argument("--strategy", required=True, help="策略名")
    p_backtest.add_argument("--codes", required=True, help="股票代码列表，逗号分隔，如 600519.SH,000001.SZ")
    p_backtest.add_argument("--start", required=True, help="回测开始日期 YYYY-MM-DD")
    p_backtest.add_argument("--end", required=True, help="回测结束日期 YYYY-MM-DD")
    p_backtest.add_argument("--output", default=None, help="报告输出路径，默认落在 strategies/reports/ 下")

    p_rate = sub.add_parser("rate", help="给出某股票在某日期的 BUY/SELL/HOLD 评级")
    p_rate.add_argument("--strategy", required=True, help="策略名")
    p_rate.add_argument("--code", required=True, help="股票代码，如 600519.SH")
    p_rate.add_argument("--date", required=True, help="评级日期 YYYY-MM-DD")

    p_screen = sub.add_parser("screen", help="全市场扫描：找出当前满足策略条件的股票")
    p_screen.add_argument("--strategy", required=True, help="策略名")
    p_screen.add_argument("--date", default=None, help="扫描日期 YYYY-MM-DD，默认各股各自最新交易日")
    p_screen.add_argument("--codes", default=None, help="联调用：指定股票池（逗号分隔），跳过全市场清单拉取")
    p_screen.add_argument("--limit", type=int, default=None, help="联调用：只扫描前N只")
    p_screen.add_argument("--lookback-days", type=int, default=None, dest="lookback_days",
                           help="行情回溯天数，默认等同 rater.DEFAULT_LOOKBACK_DAYS（400）")
    p_screen.add_argument("--rating", choices=["BUY", "SELL"], default="BUY", help="筛选目标评级")
    p_screen.add_argument("--output", default=None, help="报告输出路径，默认落在 strategies/reports/ 下")

    p_trade = sub.add_parser("trade", help="对接国金证券 QMT：生成委托预览或下单")
    trade_sub = p_trade.add_subparsers(dest="trade_command", required=True)

    trade_common = argparse.ArgumentParser(add_help=False)
    trade_common.add_argument("--strategy", required=True, help="策略名")
    trade_common.add_argument("--codes", required=True, help="股票代码列表，逗号分隔")
    trade_common.add_argument("--date", required=True, help="评级日期 YYYY-MM-DD（通常为当前交易日）")
    trade_common.add_argument("--mode", choices=["sim", "live"], default="sim", help="sim=模拟盘 live=实盘")
    trade_common.add_argument("--buy-label", default="中仓", choices=["重仓", "中仓", "轻仓"], help="BUY 信号对应的仓位档位")

    trade_sub.add_parser("plan", parents=[trade_common], help="只生成委托预览，不下单")
    p_trade_execute = trade_sub.add_parser("execute", parents=[trade_common], help="生成委托并真实下单")
    p_trade_execute.add_argument("--yes", action="store_true", help="跳过交互确认")
    p_trade_execute.add_argument("--force-outside-hours", action="store_true", help="仅sim模式：允许非交易时间下单，用于联调")
    p_trade_execute.add_argument("--i-understand-real-money", action="store_true", help="live模式必需：确认知悉这是真实资金下单")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "define":
        cmd_define(args)
    elif args.command == "backtest":
        cmd_backtest(args)
    elif args.command == "rate":
        cmd_rate(args)
    elif args.command == "screen":
        cmd_screen(args)
    elif args.command == "trade":
        if args.trade_command == "plan":
            cmd_trade_plan(args, execute=False)
        elif args.trade_command == "execute":
            cmd_trade_plan(args, execute=True)


if __name__ == "__main__":
    main()
