# -*- coding: utf-8 -*-
"""把 quant_strategy 的评级结果适配成 qmt_trading.report_parser.TradeDecision，
直接复用既有的 position_sizer.build_order_plans + qmt_gateway.QmtGateway，不重复实现下单/风控逻辑。"""
from qmt_trading.report_parser import TradeDecision
from quant_strategy.rating.rater import RatingResult, rate

DEFAULT_BUY_LABEL = "中仓"  # BUY 信号默认对应的仓位档位，可传参覆盖（重仓/中仓/轻仓）
DEFAULT_SELL_LABEL = "空仓"  # SELL 一律视为全部清仓，与 position_sizer.py 对"空仓"档位的语义一致


def to_trade_decision(rating: RatingResult, qmt_config, buy_label: str = DEFAULT_BUY_LABEL) -> TradeDecision | None:
    """HOLD 不产生委托，返回 None；BUY/SELL 转换为 TradeDecision。"""
    if rating.rating not in ("BUY", "SELL"):
        return None

    position_label = buy_label if rating.rating == "BUY" else DEFAULT_SELL_LABEL
    target_weight = qmt_config.position_weight_for_label(position_label)
    trigger_desc = rating.entry_description if rating.rating == "BUY" else rating.exit_description

    return TradeDecision(
        ticker=rating.ticker,
        action=rating.rating,
        position_label=position_label,
        target_weight=target_weight,
        rating=f"quant_strategy: {trigger_desc}" if trigger_desc else "quant_strategy",
        score=None,
        raw_price_text=f"{rating.close_price:.2f}",
        raw_stop_loss_text=None,
        report_path=f"quant_strategy::{rating.ticker}@{rating.date}",
    )


def to_trade_decisions(ratings: list, qmt_config, buy_label: str = DEFAULT_BUY_LABEL) -> list:
    decisions = []
    for r in ratings:
        d = to_trade_decision(r, qmt_config, buy_label=buy_label)
        if d is not None:
            decisions.append(d)
    return decisions


def build_plan_for_date(spec, tickers: list, date: str, mode: str = "sim", buy_label: str = DEFAULT_BUY_LABEL):
    """跑一遍策略评级，再连接 QMT 网关取实时资产/持仓/行情，最终生成委托预览计划。

    返回 (ratings, decisions, asset, plans)。仅生成预览，不下单——实际下单由调用方
    （cli.py 的 trade execute 子命令）复用 qmt_trading.qmt_gateway.QmtGateway.place_order。
    """
    from qmt_trading.config import load_config
    from qmt_trading.position_sizer import build_order_plans
    from qmt_trading.qmt_gateway import QmtGateway

    qmt_config = load_config()

    ratings = []
    for ticker in tickers:
        try:
            ratings.append(rate(spec, ticker, date))
        except Exception as e:
            print(f"[live.bridge] {ticker} 评级失败，跳过：{e}")

    decisions = to_trade_decisions(ratings, qmt_config, buy_label=buy_label)

    gateway = QmtGateway(qmt_config.userdata_path(mode), qmt_config.account_id(mode), qmt_config.account_type)
    gateway.connect(qmt_config.site_packages_path)
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
        config=qmt_config,
    )
    return ratings, decisions, asset, plans
