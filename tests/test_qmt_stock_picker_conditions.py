"""Unit tests for qmt_trading.stock_picker.conditions — pure functions, no baostock/network."""
import pandas as pd

from qmt_trading.stock_picker import conditions


def _df_from_rows(rows):
    n = len(rows)
    dates = pd.date_range("2020-01-05", periods=n, freq="W")
    df = pd.DataFrame(rows)
    df["date"] = dates
    return df


def _flat_rows(n, price=12.0, volume=100000):
    return [
        {"open": price, "high": price + 0.1, "low": price - 0.1, "close": price, "volume": volume}
        for _ in range(n)
    ]


def _condition1_positive_df():
    rows = _flat_rows(58, price=12.0)
    rows += [
        {"open": 12.0, "high": 12.1, "low": 11.9, "close": 12.0, "volume": 100000},   # week -12
        {"open": 12.0, "high": 12.05, "low": 11.65, "close": 11.7, "volume": 100000},  # week -11
        {"open": 11.7, "high": 11.75, "low": 11.35, "close": 11.4, "volume": 100000},  # week -10
        {"open": 11.4, "high": 11.45, "low": 11.05, "close": 11.1, "volume": 100000},  # week -9
        {"open": 11.1, "high": 11.15, "low": 10.75, "close": 10.8, "volume": 100000},  # week -8
        {"open": 10.8, "high": 10.85, "low": 10.45, "close": 10.5, "volume": 100000},  # week -7
        {"open": 10.5, "high": 10.55, "low": 10.15, "close": 10.2, "volume": 100000},  # week -6
        {"open": 10.2, "high": 10.25, "low": 9.95, "close": 10.0, "volume": 100000},   # week -5
        {"open": 9.8, "high": 10.0, "low": 9.7, "close": 9.85, "volume": 80000},       # week -4 (doji)
        {"open": 9.85, "high": 10.0, "low": 9.65, "close": 9.8, "volume": 75000},      # week -3 (doji)
        {"open": 9.8, "high": 10.05, "low": 9.65, "close": 9.9, "volume": 85000},      # week -2 (doji)
        {"open": 9.9, "high": 11.6, "low": 9.85, "close": 11.5, "volume": 150000},     # week -1 breakout
    ]
    return _df_from_rows(rows)


def test_condition_1_positive():
    df = _condition1_positive_df()
    hit, detail = conditions.condition_1(df)
    assert hit is True, detail


def test_condition_1_fails_without_volume_expansion():
    df = _condition1_positive_df()
    # 把突破周成交量调低，破坏放量条件，其余不变
    df.loc[df.index[-1], "volume"] = 50000
    hit, detail = conditions.condition_1(df)
    assert hit is False
    assert detail["volume_ratio"] is not None and detail["volume_ratio"] < 1.5


def test_condition_1_skips_short_history():
    df = _condition1_positive_df().iloc[-10:].reset_index(drop=True)
    hit, detail = conditions.condition_1(df)
    assert hit is False
    assert detail.get("skip") == "history_too_short"


def _condition2_base_rows(n_base=60):
    rows = _flat_rows(n_base, price=10.0)
    rows += [
        {"open": 10.0, "high": 10.05, "low": 9.95, "close": 10.0, "volume": 100000},  # week -5
        {"open": 10.0, "high": 10.1, "low": 9.95, "close": 10.05, "volume": 100000},  # week -4
        {"open": 10.0, "high": 10.05, "low": 9.9, "close": 10.0, "volume": 100000},   # week -3
        {"open": 10.05, "high": 10.15, "low": 9.95, "close": 10.1, "volume": 100000}, # week -2
        {"open": 10.1, "high": 10.6, "low": 10.05, "close": 10.5, "volume": 100000},  # week -1 breakout
    ]
    return rows


def test_condition_2_conservative_breakout():
    df = _df_from_rows(_condition2_base_rows())
    hit, detail = conditions.condition_2(df, aggressive=False)
    assert hit is True, detail


def test_condition_2_conservative_fails_when_no_new_high():
    rows = _condition2_base_rows()
    rows[-1]["close"] = 10.1  # 未突破前4周最高价(10.15)
    df = _df_from_rows(rows)
    hit, _ = conditions.condition_2(df, aggressive=False)
    assert hit is False


def test_condition_2_aggressive_is_looser_than_conservative():
    # 前3周收盘/开盘最高价 明显低于 前4周最高价(含更早一周的高点)时，
    # aggressive 版本应该比 conservative 版本更容易触发。
    rows = _condition2_base_rows()
    rows[-5]["high"] = 10.9  # 只抬高 week -5 的最高价（不在 aggressive 的3周窗口内）
    rows[-1]["close"] = 10.3  # 突破不了 conservative 的前4周高点，但能突破 aggressive 的前3周收盘/开盘高点
    df = _df_from_rows(rows)

    hit_conservative, _ = conditions.condition_2(df, aggressive=False)
    hit_aggressive, _ = conditions.condition_2(df, aggressive=True)
    assert hit_conservative is False
    assert hit_aggressive is True


def _condition3_uptrend_df(n=70, step=0.05, base=10.0, last_volume=130000):
    rows = []
    for i in range(n):
        close = base + step * i
        rows.append(
            {"open": close - 0.02, "high": close + 0.05, "low": close - 0.05, "close": close, "volume": 100000}
        )
    rows[-1]["volume"] = last_volume
    return _df_from_rows(rows)


def test_condition_3_positive_uptrend():
    df = _condition3_uptrend_df()
    hit, detail = conditions.condition_3(df)
    assert hit is True, detail


def test_condition_3_fails_without_volume_expansion():
    df = _condition3_uptrend_df(last_volume=100000)
    hit, detail = conditions.condition_3(df)
    assert hit is False
    assert detail["volume_expand_ok"] is False


def test_condition_3_fails_when_mas_not_bullish_aligned():
    df = _condition3_uptrend_df(step=-0.02)  # 改成下降趋势，均线不再多头排列
    hit, detail = conditions.condition_3(df)
    assert hit is False
    assert detail["bullish_alignment"] is False


def _condition4_pileup_df():
    n_base = 60
    rows = _flat_rows(n_base, price=10.0, volume=100000)
    rows += [
        {"open": 10.0, "high": 10.1, "low": 9.95, "close": 10.05, "volume": 100000},  # week -8
        {"open": 10.05, "high": 10.15, "low": 9.95, "close": 10.1, "volume": 100000}, # week -7
        {"open": 11.0, "high": 12.2, "low": 10.9, "close": 12.0, "volume": 300000},   # week -6 堆量
        {"open": 12.0, "high": 12.0, "low": 11.7, "close": 11.8, "volume": 90000},    # week -5 回调
        {"open": 11.8, "high": 11.85, "low": 11.5, "close": 11.6, "volume": 80000},   # week -4
        {"open": 11.6, "high": 11.65, "low": 11.4, "close": 11.5, "volume": 70000},   # week -3
        {"open": 11.5, "high": 11.55, "low": 11.3, "close": 11.4, "volume": 65000},   # week -2
        {"open": 11.4, "high": 11.45, "low": 11.2, "close": 11.3, "volume": 60000},   # week -1
    ]
    return _df_from_rows(rows)


def test_condition_4_positive_pullback_after_pileup():
    df = _condition4_pileup_df()
    hit, detail = conditions.condition_4(df)
    assert hit is True, detail
    assert detail["pile_week_found"] is True


def test_condition_4_fails_when_pullback_breaks_ma20():
    df = _condition4_pileup_df()
    # 最新周直接砸穿MA20，不再是"温和回调"
    df.loc[df.index[-1], "close"] = 8.0
    hit, detail = conditions.condition_4(df)
    assert hit is False


def test_condition_4_no_pileup_found():
    df = _df_from_rows(_flat_rows(70, price=10.0, volume=100000))
    hit, detail = conditions.condition_4(df)
    assert hit is False
    assert detail == {"pile_week_found": False}


def test_evaluate_all_combine_modes(monkeypatch):
    fake_funcs = {
        1: lambda df: (True, {}),
        2: lambda df, aggressive=False: (True, {}),
        3: lambda df: (False, {}),
        4: lambda df: (False, {}),
    }
    monkeypatch.setattr(conditions, "CONDITION_FUNCS", fake_funcs)
    df = pd.DataFrame()

    result_all = conditions.evaluate_all(df, mode="all")
    assert result_all["matched"] == [1, 2]
    assert result_all["overall_hit"] is False

    result_any = conditions.evaluate_all(df, mode="any")
    assert result_any["matched"] == [1, 2]
    assert result_any["overall_hit"] is True
