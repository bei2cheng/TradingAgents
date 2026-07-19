"""Unit tests for quant_strategy.live.bridge — adapts ratings into qmt_trading.TradeDecision, mocks QMT entirely."""
from qmt_trading.config import QmtConfig
from quant_strategy.live.bridge import DEFAULT_SELL_LABEL, to_trade_decision, to_trade_decisions
from quant_strategy.rating.rater import RatingResult


def _config():
    return QmtConfig(
        weight_heavy=0.35, weight_medium=0.25, weight_light=0.15, weight_empty=0.0,
        stock_whitelist=("600519.SH", "000002.SZ"),
    )


def test_hold_rating_produces_no_decision():
    rating = RatingResult(ticker="600519.SH", date="2026-07-18", rating="HOLD", close_price=1700.0)
    assert to_trade_decision(rating, _config()) is None


def test_buy_rating_maps_to_default_position_label_and_weight():
    rating = RatingResult(
        ticker="600519.SH", date="2026-07-18", rating="BUY", close_price=1700.0,
        triggered_entry=True, entry_description="ma_window5 cross_above ma_window20",
    )
    decision = to_trade_decision(rating, _config())

    assert decision.ticker == "600519.SH"
    assert decision.action == "BUY"
    assert decision.position_label == "中仓"
    assert decision.target_weight == 0.25
    assert "cross_above" in decision.rating
    assert decision.is_actionable


def test_sell_rating_maps_to_full_liquidation_label():
    rating = RatingResult(
        ticker="000002.SZ", date="2026-07-18", rating="SELL", close_price=8.0,
        triggered_exit=True, exit_description="ma_window5 cross_below ma_window20",
    )
    decision = to_trade_decision(rating, _config())

    assert decision.action == "SELL"
    assert decision.position_label == DEFAULT_SELL_LABEL
    assert decision.target_weight == 0.0


def test_buy_label_override_is_respected():
    rating = RatingResult(ticker="600519.SH", date="2026-07-18", rating="BUY", close_price=1700.0)
    decision = to_trade_decision(rating, _config(), buy_label="重仓")
    assert decision.position_label == "重仓"
    assert decision.target_weight == 0.35


def test_to_trade_decisions_filters_out_hold():
    ratings = [
        RatingResult(ticker="600519.SH", date="2026-07-18", rating="BUY", close_price=1700.0),
        RatingResult(ticker="000002.SZ", date="2026-07-18", rating="HOLD", close_price=8.0),
    ]
    decisions = to_trade_decisions(ratings, _config())
    assert len(decisions) == 1
    assert decisions[0].ticker == "600519.SH"
