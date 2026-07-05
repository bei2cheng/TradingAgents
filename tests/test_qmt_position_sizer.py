"""Unit tests for qmt_trading.position_sizer — pure functions, no QMT dependency."""
from qmt_trading.config import QmtConfig
from qmt_trading.position_sizer import PositionInfo, build_order_plans
from qmt_trading.report_parser import TradeDecision


def _decision(ticker, action, position_label, target_weight, warning=None):
    return TradeDecision(
        ticker=ticker,
        action=action,
        position_label=position_label,
        target_weight=target_weight,
        rating=None,
        score=None,
        raw_price_text=None,
        raw_stop_loss_text=None,
        report_path=f"reports/{ticker}/fake.md",
        warning=warning,
    )


def _config(**overrides):
    base = dict(
        max_single_stock_pct=0.20,
        max_total_position_pct=0.80,
        lot_size=100,
        slippage_pct=0.005,
        min_order_notional=1000.0,
        weight_heavy=0.35,
        weight_medium=0.25,
        weight_light=0.15,
        weight_empty=0.0,
        stock_whitelist=("A.SH", "B.SH", "C.SH"),
    )
    base.update(overrides)
    return QmtConfig(**base)


def test_buy_sizes_to_target_weight_within_cash():
    decisions = [_decision("A.SH", "BUY", "轻仓", 0.15)]
    plans = build_order_plans(
        decisions,
        total_asset=100_000,
        cash=100_000,
        positions={},
        latest_prices={"A.SH": 10.0},
        config=_config(),
        log=lambda *_: None,
    )
    assert len(plans) == 1
    plan = plans[0]
    assert plan.side == "BUY"
    # 目标市值 15000 / 10元 = 1500股 -> 取整到百手 = 1500
    assert plan.shares == 1500
    assert plan.limit_price > plan.ref_price  # 买入加滑点


def test_single_stock_cap_enforced():
    decisions = [_decision("A.SH", "BUY", "重仓", 0.35)]  # 35% 超过单股上限20%
    plans = build_order_plans(
        decisions,
        total_asset=100_000,
        cash=100_000,
        positions={},
        latest_prices={"A.SH": 10.0},
        config=_config(),
        log=lambda *_: None,
    )
    plan = plans[0]
    # 封顶后目标市值 20000 / 10 = 2000股
    assert plan.shares == 2000


def test_total_position_cap_scales_down_proportionally():
    decisions = [
        _decision("A.SH", "BUY", "重仓", 0.35),
        _decision("B.SH", "BUY", "重仓", 0.35),
        _decision("C.SH", "BUY", "重仓", 0.35),
    ]
    # 每只先被单股上限(20%)封顶 -> 合计60%，未超过总仓位上限80%，不缩放
    plans = build_order_plans(
        decisions,
        total_asset=100_000,
        cash=100_000,
        positions={},
        latest_prices={"A.SH": 10.0, "B.SH": 10.0, "C.SH": 10.0},
        config=_config(max_single_stock_pct=0.35, max_total_position_pct=0.60),
        log=lambda *_: None,
    )
    total_notional = sum(p.notional for p in plans)
    # 三只各35% = 105%，超过总仓位上限60%，按比例缩放到 60% * 100000 = 60000
    assert abs(total_notional - 60_000) < 400  # 允许百手取整误差


def test_sell_with_empty_label_liquidates_full_position():
    decisions = [_decision("A.SH", "SELL", "空仓", 0.0)]
    plans = build_order_plans(
        decisions,
        total_asset=100_000,
        cash=0,
        positions={"A.SH": PositionInfo(volume=1234, can_use_volume=1234, market_value=12340)},
        latest_prices={"A.SH": 10.0},
        config=_config(),
        log=lambda *_: None,
    )
    plan = plans[0]
    assert plan.side == "SELL"
    assert plan.shares == 1234  # 全部清仓，不做百手取整


def test_hold_action_produces_no_order():
    decisions = [_decision("A.SH", "HOLD", None, None)]
    plans = build_order_plans(
        decisions,
        total_asset=100_000,
        cash=100_000,
        positions={"A.SH": PositionInfo(volume=100, can_use_volume=100, market_value=1000)},
        latest_prices={"A.SH": 10.0},
        config=_config(),
        log=lambda *_: None,
    )
    assert plans == []


def test_ticker_outside_whitelist_is_ignored():
    decisions = [_decision("ZZZ.SH", "BUY", "轻仓", 0.15)]
    plans = build_order_plans(
        decisions,
        total_asset=100_000,
        cash=100_000,
        positions={},
        latest_prices={"ZZZ.SH": 10.0},
        config=_config(),
        log=lambda *_: None,
    )
    assert plans == []


def test_order_below_min_notional_is_skipped():
    decisions = [_decision("A.SH", "BUY", "轻仓", 0.15)]
    plans = build_order_plans(
        decisions,
        total_asset=1_000,  # 目标市值 150 元，低于最小下单金额
        cash=1_000,
        positions={},
        latest_prices={"A.SH": 10.0},
        config=_config(min_order_notional=1000.0),
        log=lambda *_: None,
    )
    assert plans == []
