# -*- coding: utf-8 -*-
"""周线选股策略条件判断：纯函数，输入周线 DataFrame（按日期升序，列 open/high/low/close/volume），
不依赖网络/baostock，方便单测。

约定：df.iloc[-1] 是最新（可能未走完）的一周。
"""
import pandas as pd

from qmt_trading.stock_picker.indicators import body_ratio, ma

# 至少需要的周线根数（MA60 在倒数第3根仍需完整窗口 -> 60 + 2，留一些余量）
MIN_WEEKS = 65

# 可调阈值，集中放在这里方便调参
DOWNTREND_LOOKBACK = 8       # 震荡前，判断下跌的回溯周数
DOWNTREND_MIN_DROP = -0.08   # 震荡前累计跌幅阈值
CONSOLIDATION_WEEKS = 3      # 连续十字星/短实体的周数
DOJI_BODY_RATIO_MAX = 0.30   # 十字星/短实体：实体占振幅比例上限
BREAKOUT_VOLUME_MULT = 1.5   # 突破周相对震荡期均量的放量倍数

BREAKOUT_PRIOR_WEEKS = 4     # 策略2保守版：突破前几周高点
AGGRESSIVE_PRIOR_WEEKS = 3   # 策略2激进版：突破前几周收盘/开盘高点

MA_TURN_UP_LOOKBACK = 2      # 均线拐头判断：与几周前的均线值比较
MAX_DEVIATION_FROM_MA5 = 0.15  # 股价偏离5周线的最大比例
VOLUME_EXPAND_LOOKBACK = 10  # 策略3量能放大参考的均量周数
VOLUME_EXPAND_MULT = 1.1

PILE_UP_LOOKBACK = 8         # 策略4：在最近几周里找堆量周（不含最新一周）
PILE_UP_BASE_WEEKS = 10      # 堆量周相对之前几周均量比较
PILE_UP_VOLUME_MULT = 2.0    # 堆量倍数
PULLBACK_VOLUME_SHRINK_MULT = 0.7  # 回调期缩量倍数


def _has_enough_history(df: pd.DataFrame) -> bool:
    return len(df) >= MIN_WEEKS


def condition_1(df: pd.DataFrame) -> tuple:
    """周线下跌后持续震荡，连续三周十字星/短实体，放量阳线，股价站稳5周线上方。"""
    if not _has_enough_history(df):
        return False, {"skip": "history_too_short"}

    close, open_, high, low, volume = df["close"], df["open"], df["high"], df["low"], df["volume"]

    downtrend_ret = (close.iloc[-1 - CONSOLIDATION_WEEKS] - close.iloc[-1 - CONSOLIDATION_WEEKS - DOWNTREND_LOOKBACK]) / close.iloc[-1 - CONSOLIDATION_WEEKS - DOWNTREND_LOOKBACK]
    downtrend_ok = downtrend_ret <= DOWNTREND_MIN_DROP

    consolidation_idx = range(-1 - CONSOLIDATION_WEEKS, -1)  # 最新一周之前的连续3周
    body_ratios = [
        body_ratio(open_.iloc[i], close.iloc[i], high.iloc[i], low.iloc[i]) for i in consolidation_idx
    ]
    consolidation_ok = all(b <= DOJI_BODY_RATIO_MAX for b in body_ratios)

    latest_bullish = close.iloc[-1] > open_.iloc[-1]
    consolidation_vol_avg = volume.iloc[list(consolidation_idx)].mean()
    volume_ok = consolidation_vol_avg > 0 and volume.iloc[-1] >= BREAKOUT_VOLUME_MULT * consolidation_vol_avg

    ma5 = ma(close, 5)
    above_ma5 = close.iloc[-1] > ma5.iloc[-1]
    ma5_turning_up = ma5.iloc[-1] >= ma5.iloc[-1 - MA_TURN_UP_LOOKBACK]

    hit = bool(downtrend_ok and consolidation_ok and latest_bullish and volume_ok and above_ma5 and ma5_turning_up)
    return hit, {
        "downtrend_ret": round(float(downtrend_ret), 4),
        "downtrend_ok": bool(downtrend_ok),
        "body_ratios": [round(b, 3) for b in body_ratios],
        "consolidation_ok": bool(consolidation_ok),
        "latest_bullish": bool(latest_bullish),
        "volume_ratio": round(float(volume.iloc[-1] / consolidation_vol_avg), 3) if consolidation_vol_avg else None,
        "above_ma5": bool(above_ma5),
        "ma5_turning_up": bool(ma5_turning_up),
    }


def condition_2(df: pd.DataFrame, aggressive: bool = False) -> tuple:
    """本周收盘突破前四周最高价；激进版（行情好时用）改为门槛更低的判断：
    本周收盘价超过前三周最高收盘/开盘价即可（不是在保守版基础上叠加，而是替换判断口径，
    因为前三周收盘/开盘的最高值恒小于等于前四周最高价，叠加等于没有放宽）。
    """
    if not _has_enough_history(df):
        return False, {"skip": "history_too_short"}

    close, open_, high = df["close"], df["open"], df["high"]

    if aggressive:
        prior_window = slice(-1 - AGGRESSIVE_PRIOR_WEEKS, -1)
        ref = max(close.iloc[prior_window].max(), open_.iloc[prior_window].max())
        ok = close.iloc[-1] > ref
        detail = {
            "mode": "aggressive",
            "prior_3w_close_open_high": round(float(ref), 3),
            "close": round(float(close.iloc[-1]), 3),
            "ok": bool(ok),
        }
    else:
        ref = high.iloc[-1 - BREAKOUT_PRIOR_WEEKS:-1].max()
        ok = close.iloc[-1] > ref
        detail = {
            "mode": "conservative",
            "prior_4w_high": round(float(ref), 3),
            "close": round(float(close.iloc[-1]), 3),
            "ok": bool(ok),
        }

    return bool(ok), detail


def condition_3(df: pd.DataFrame) -> tuple:
    """5周线/20周线拐头向上，均线多头排列，股价不过分远离均线，成交量放大。"""
    if not _has_enough_history(df):
        return False, {"skip": "history_too_short"}

    close, volume = df["close"], df["volume"]
    ma5, ma10, ma20, ma60 = ma(close, 5), ma(close, 10), ma(close, 20), ma(close, 60)

    ma5_up = ma5.iloc[-1] > ma5.iloc[-1 - MA_TURN_UP_LOOKBACK]
    ma20_up = ma20.iloc[-1] > ma20.iloc[-1 - MA_TURN_UP_LOOKBACK]
    turning_up_ok = bool(ma5_up and ma20_up)

    bullish_alignment = bool(ma5.iloc[-1] > ma10.iloc[-1] > ma20.iloc[-1] > ma60.iloc[-1])

    deviation = abs(close.iloc[-1] - ma5.iloc[-1]) / ma5.iloc[-1]
    not_too_far_ok = deviation <= MAX_DEVIATION_FROM_MA5

    vol_avg = volume.iloc[-1 - VOLUME_EXPAND_LOOKBACK:-1].mean()
    volume_expand_ok = vol_avg > 0 and volume.iloc[-1] >= VOLUME_EXPAND_MULT * vol_avg

    hit = bool(turning_up_ok and bullish_alignment and not_too_far_ok and volume_expand_ok)
    return hit, {
        "ma5_up": bool(ma5_up),
        "ma20_up": bool(ma20_up),
        "bullish_alignment": bullish_alignment,
        "deviation_from_ma5": round(float(deviation), 4),
        "not_too_far_ok": bool(not_too_far_ok),
        "volume_ratio": round(float(volume.iloc[-1] / vol_avg), 3) if vol_avg else None,
        "volume_expand_ok": bool(volume_expand_ok),
    }


def condition_4(df: pd.DataFrame) -> tuple:
    """周线堆量后温和回调（未破位、缩量）是机会。"""
    if not _has_enough_history(df):
        return False, {"skip": "history_too_short"}

    close, volume = df["close"], df["volume"]
    ma20 = ma(close, 20)
    n = len(df)

    pile_idx = None
    # 最近 PILE_UP_LOOKBACK 周（不含最新一周）里，从近到远找堆量周
    for offset in range(2, PILE_UP_LOOKBACK + 2):
        idx = n - offset
        base_start = idx - PILE_UP_BASE_WEEKS
        if base_start < 0:
            continue
        base_avg = volume.iloc[base_start:idx].mean()
        if base_avg > 0 and volume.iloc[idx] >= PILE_UP_VOLUME_MULT * base_avg:
            pile_idx = idx
            break

    if pile_idx is None:
        return False, {"pile_week_found": False}

    pullback_ok = bool(close.iloc[-1] < close.iloc[pile_idx] and close.iloc[-1] >= ma20.iloc[-1])
    shrink_ok = bool(volume.iloc[-1] < PULLBACK_VOLUME_SHRINK_MULT * volume.iloc[pile_idx])

    hit = bool(pullback_ok and shrink_ok)
    return hit, {
        "pile_week_found": True,
        "pile_week_date": str(df["date"].iloc[pile_idx]) if "date" in df.columns else None,
        "pullback_ok": pullback_ok,
        "shrink_ok": shrink_ok,
    }


CONDITION_FUNCS = {
    1: condition_1,
    2: condition_2,
    3: condition_3,
    4: condition_4,
}


def evaluate_all(df: pd.DataFrame, aggressive: bool = False, mode: str = "all") -> dict:
    """跑全部4条策略，返回每条的命中情况 + 按 mode 汇总的整体命中结果。

    mode="all": 4条全部命中才算整体命中；mode="any": 命中任意一条即可。
    """
    results = {}
    for idx, func in CONDITION_FUNCS.items():
        if idx == 2:
            hit, detail = func(df, aggressive=aggressive)
        else:
            hit, detail = func(df)
        results[idx] = {"hit": hit, "detail": detail}

    matched = [idx for idx, r in results.items() if r["hit"]]
    if mode == "any":
        overall_hit = len(matched) > 0
    else:
        overall_hit = len(matched) == len(CONDITION_FUNCS)

    return {"conditions": results, "matched": matched, "overall_hit": overall_hit}
