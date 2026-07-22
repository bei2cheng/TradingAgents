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
            log(f"[跳过] {d.ticker} 操作方向为 HOLD，无需下单")
            continue
        if not d.is_actionable:
            log(f"[跳过] {d.ticker} 决策不可执行（action={d.action}, target_weight={d.target_weight}）")
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

    # 4) 逐股票计算买卖差额 -> 理论股数（此时先不考虑现金是否够用）
    raw = []  # (ticker, decision, target_weight, side, shares, price)
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
                log(f"[跳过] {ticker} 已空仓，无可卖持仓")
                continue
            shares = pos.can_use_volume
            side = "SELL"
        elif delta_value > 0:
            side = "BUY"
            shares = math.floor(delta_value / price / config.lot_size) * config.lot_size
        elif delta_value < 0:
            side = "SELL"
            shares = math.floor(-delta_value / price / config.lot_size) * config.lot_size
            shares = min(shares, pos.can_use_volume)
        else:
            log(f"[跳过] {ticker} 当前持仓已等于目标市值，无需调仓")
            continue

        if shares <= 0:
            log(f"[跳过] {ticker} 调仓差额不足一手（{config.lot_size}股），无需下单")
            continue

        raw.append((ticker, decision, target_weight, side, shares, price))

    # 5) 若全部 BUY 所需资金合计超过可用现金，按比例统一缩放所有 BUY 订单，
    #    避免按 STOCK_LIST 顺序"先到先得"占满现金，导致排在后面的股票被静默跳过
    buy_total_notional = sum(shares * price for _, _, _, side, shares, price in raw if side == "BUY")
    if buy_total_notional > cash and buy_total_notional > 0:
        scale = max(cash, 0) / buy_total_notional
        log(
            f"[风控] 全部 BUY 所需资金合计 {buy_total_notional:.0f} 超过可用现金 {cash:.0f}，"
            f"按比例缩放 {scale:.3f}"
        )
        scaled = []
        for ticker, decision, target_weight, side, shares, price in raw:
            if side == "BUY":
                shares = math.floor(shares * scale / config.lot_size) * config.lot_size
            scaled.append((ticker, decision, target_weight, side, shares, price))
        raw = scaled

    # 6) 生成最终委托单
    plans = []
    for ticker, decision, target_weight, side, shares, price in raw:
        if shares <= 0:
            log(f"[跳过] {ticker} 按可用现金比例缩放后不足一手（{config.lot_size}股），无需下单")
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
