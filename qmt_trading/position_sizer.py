# -*- coding: utf-8 -*-
"""根据 TradeDecision + 账户资产/持仓/行情，计算具体的委托单（纯函数，不依赖 QMT）。"""
import math
from dataclasses import dataclass

from qmt_trading.report_parser import TradeDecision


@dataclass
class PositionInfo:
    volume: int = 0
    can_use_volume: int = 0
    market_value: float = 0.0


@dataclass
class OrderPlan:
    ticker: str
    side: str  # "BUY" / "SELL"
    shares: int
    ref_price: float
    limit_price: float
    notional: float
    reason: str


def build_order_plans(
    decisions: list[TradeDecision],
    total_asset: float,
    cash: float,
    positions: dict[str, PositionInfo],
    latest_prices: dict[str, float],
    config,
    log=print,
) -> list[OrderPlan]:
    whitelist = set(config.stock_whitelist)

    # 1) 目标权重（仅白名单内、可执行的 BUY/SELL 决策；HOLD/无法解析 一律跳过）
    targets = {}  # ticker -> (target_weight, decision)
    for d in decisions:
        if d.ticker not in whitelist:
            log(f"[跳过] {d.ticker} 不在白名单 STOCK_LIST 内")
            continue
        if d.warning:
            log(f"[跳过] {d.ticker} {d.warning}")
            continue
        if d.action == "HOLD":
            continue
        if not d.is_actionable:
            continue
        targets[d.ticker] = d

    # 2) 单股目标权重先封顶
    capped = {t: min(d.target_weight, config.max_single_stock_pct) for t, d in targets.items()}

    # 3) 所有 BUY 方向的目标权重求和，超过总仓位上限则整体按比例缩放
    buy_tickers = [t for t, d in targets.items() if d.action == "BUY"]
    buy_weight_sum = sum(capped[t] for t in buy_tickers)
    if buy_weight_sum > config.max_total_position_pct and buy_weight_sum > 0:
        scale = config.max_total_position_pct / buy_weight_sum
        log(
            f"[风控] 全部 BUY 目标仓位合计 {buy_weight_sum:.1%} 超过总仓位上限 "
            f"{config.max_total_position_pct:.1%}，按比例缩放 {scale:.3f}"
        )
        for t in buy_tickers:
            capped[t] *= scale

    # 4) 逐股票计算买卖差额 -> 股数
    plans = []
    for ticker, decision in targets.items():
        price = latest_prices.get(ticker)
        if not price or price <= 0:
            log(f"[跳过] {ticker} 未获取到有效最新价，无法计算下单数量")
            continue

        pos = positions.get(ticker, PositionInfo())
        target_weight = capped[ticker]
        target_value = total_asset * target_weight
        delta_value = target_value - pos.market_value

        if decision.action == "SELL" and decision.position_label == "空仓":
            # 空仓档位 = 完全清仓，直接清空可用持仓，避免百手取整残留
            if pos.can_use_volume <= 0:
                continue
            shares = pos.can_use_volume
            side = "SELL"
        elif delta_value > 0:
            side = "BUY"
            max_affordable = math.floor(cash / price / config.lot_size) * config.lot_size
            shares = math.floor(delta_value / price / config.lot_size) * config.lot_size
            shares = min(shares, max_affordable)
        elif delta_value < 0:
            side = "SELL"
            shares = math.floor(-delta_value / price / config.lot_size) * config.lot_size
            shares = min(shares, pos.can_use_volume)
        else:
            continue

        if shares <= 0:
            continue

        notional = shares * price
        if notional < config.min_order_notional:
            log(f"[跳过] {ticker} 订单金额 {notional:.0f} 低于最小下单金额 {config.min_order_notional:.0f}")
            continue

        slippage = config.slippage_pct if side == "BUY" else -config.slippage_pct
        limit_price = round(price * (1 + slippage), 2)

        plans.append(
            OrderPlan(
                ticker=ticker,
                side=side,
                shares=int(shares),
                ref_price=price,
                limit_price=limit_price,
                notional=notional,
                reason=f"{decision.action}/{decision.position_label}(目标{target_weight:.1%})",
            )
        )
        if side == "BUY":
            cash -= notional  # 后续股票的可用现金随之递减

    return plans


def format_order_plans(plans: list[OrderPlan]) -> str:
    if not plans:
        return "（无可执行的委托单）"
    lines = ["| 股票 | 方向 | 股数 | 参考价 | 限价 | 金额 | 依据 |", "|---|---|---|---|---|---|---|"]
    for p in plans:
        lines.append(
            f"| {p.ticker} | {p.side} | {p.shares} | {p.ref_price:.2f} | "
            f"{p.limit_price:.2f} | {p.notional:.0f} | {p.reason} |"
        )
    return "\n".join(lines)
