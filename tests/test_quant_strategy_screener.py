"""Unit tests for quant_strategy.rating.screener — full-market scan over synthetic per-ticker data."""
import pandas as pd

from quant_strategy.rating import screener
from quant_strategy.strategy.schema import Condition, IndicatorRef, Rule, StrategySpec


def _df(closes):
    dates = pd.date_range("2024-01-01", periods=len(closes), freq="B")
    closes = pd.Series(closes, index=dates)
    return pd.DataFrame({
        "open": closes, "high": closes, "low": closes, "close": closes,
        "volume": pd.Series([100.0] * len(closes), index=dates),
    }, index=dates)


def _spec():
    entry = Rule.leaf(Condition(left=IndicatorRef(name="close"), comparator="gte", right=20.0))
    exit_rule = Rule.leaf(Condition(left=IndicatorRef(name="close"), comparator="lte", right=5.0))
    return StrategySpec(name="t", description="", mode="dsl", entry_rule=entry, exit_rule=exit_rule)


def test_screen_market_only_matches_target_rating(monkeypatch):
    data = {
        "600519.SH": _df([10.0, 10.0, 20.0]),  # last close=20 -> BUY
        "000001.SZ": _df([10.0, 10.0, 10.0]),  # last close=10 -> HOLD
        "000002.SZ": _df([10.0, 10.0, 5.0]),   # last close=5 -> SELL
    }
    monkeypatch.setattr(screener, "fetch_many", lambda tickers, start, end: data)

    matches, stats = screener.screen_market(
        _spec(), codes=list(data.keys()), target_rating="BUY"
    )

    assert stats["total"] == 3
    assert stats["matched"] == 1
    assert len(matches) == 1
    assert matches[0]["股票代码"] == "600519.SH"
    assert matches[0]["评级"] == "BUY"


def test_screen_market_can_filter_sell(monkeypatch):
    data = {
        "600519.SH": _df([10.0, 10.0, 20.0]),
        "000002.SZ": _df([10.0, 10.0, 5.0]),
    }
    monkeypatch.setattr(screener, "fetch_many", lambda tickers, start, end: data)

    matches, stats = screener.screen_market(
        _spec(), codes=list(data.keys()), target_rating="SELL"
    )

    assert stats["matched"] == 1
    assert matches[0]["股票代码"] == "000002.SZ"


def test_screen_market_skips_missing_data_without_aborting(monkeypatch):
    data = {
        "600519.SH": _df([10.0, 10.0, 20.0]),
        "000001.SZ": None,  # fetch_many failed for this ticker
    }
    monkeypatch.setattr(screener, "fetch_many", lambda tickers, start, end: data)

    matches, stats = screener.screen_market(
        _spec(), codes=list(data.keys()), target_rating="BUY"
    )

    assert stats["total"] == 2
    assert stats["skipped"] == 1
    assert stats["matched"] == 1


def test_screen_market_limit_truncates_universe(monkeypatch):
    data = {
        "600519.SH": _df([10.0, 10.0, 20.0]),
        "000001.SZ": _df([10.0, 10.0, 20.0]),
        "000002.SZ": _df([10.0, 10.0, 20.0]),
    }
    captured = {}

    def fake_fetch_many(tickers, start, end):
        captured["tickers"] = tickers
        return {t: data[t] for t in tickers}

    monkeypatch.setattr(screener, "fetch_many", fake_fetch_many)

    matches, stats = screener.screen_market(
        _spec(), codes=list(data.keys()), limit=1, target_rating="BUY"
    )

    assert stats["total"] == 1
    assert len(captured["tickers"]) == 1


def test_screen_market_explicit_date_truncates_each_ticker(monkeypatch):
    df = _df([10.0, 10.0, 20.0, 5.0])  # index[2] close=20 (BUY), index[3] close=5 (SELL)
    cutoff = str(df.index[2].date())
    monkeypatch.setattr(screener, "fetch_many", lambda tickers, start, end: {"600519.SH": df})

    matches, stats = screener.screen_market(
        _spec(), date=cutoff, codes=["600519.SH"], target_rating="BUY"
    )

    assert stats["matched"] == 1
    assert matches[0]["日期"] == cutoff


def test_generate_screen_report_handles_no_matches():
    stats = {"total": 5, "fetched": 5, "skipped": 0, "matched": 0, "elapsed": 1.0,
              "date": "2026-07-18", "target_rating": "BUY"}
    report = screener.generate_screen_report([], stats, _spec())
    assert "未筛出" in report


def test_default_screen_report_path_uses_strategy_and_date():
    path = screener.default_screen_report_path("bot_vol_rally", "2026-07-18")
    assert "bot_vol_rally" in path
    assert "2026-07-18" in path
    assert path.endswith(".md")
