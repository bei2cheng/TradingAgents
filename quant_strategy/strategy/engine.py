# -*- coding: utf-8 -*-
"""StrategyEngine：统一入口，屏蔽 DSL 规则求值 vs codegen 两种实现的差异。"""
import pandas as pd

from quant_strategy.strategy import indicators as ind
from quant_strategy.strategy.schema import Condition, IndicatorRef, Rule, StrategySpec

BUY, SELL, HOLD = "BUY", "SELL", "HOLD"


def _resolve(df: pd.DataFrame, value) -> pd.Series:
    if isinstance(value, IndicatorRef):
        return ind.resolve_indicator(df, value)
    return pd.Series(float(value), index=df.index)


def evaluate_condition(df: pd.DataFrame, condition: Condition) -> pd.Series:
    left = _resolve(df, condition.left)
    right = _resolve(df, condition.right)

    if condition.comparator == "gt":
        return left > right
    if condition.comparator == "gte":
        return left >= right
    if condition.comparator == "lt":
        return left < right
    if condition.comparator == "lte":
        return left <= right
    if condition.comparator == "cross_above":
        return (left.shift(1) <= right.shift(1)) & (left > right)
    if condition.comparator == "cross_below":
        return (left.shift(1) >= right.shift(1)) & (left < right)

    raise ValueError(f"未知比较符：{condition.comparator}")


def evaluate_rule(df: pd.DataFrame, rule: Rule | None) -> pd.Series:
    if rule is None:
        return pd.Series(False, index=df.index)
    if rule.op == "leaf":
        return evaluate_condition(df, rule.condition).fillna(False)
    if rule.op == "and":
        result = pd.Series(True, index=df.index)
        for child in rule.children:
            result &= evaluate_rule(df, child)
        return result
    if rule.op == "or":
        result = pd.Series(False, index=df.index)
        for child in rule.children:
            result |= evaluate_rule(df, child)
        return result
    if rule.op == "not":
        return ~evaluate_rule(df, rule.children[0])

    raise ValueError(f"未知规则组合符：{rule.op}")


def generate_signals(spec: StrategySpec, df: pd.DataFrame) -> pd.Series:
    """给定策略与OHLCV数据，返回逐行 BUY/SELL/HOLD 信号，index 与 df 对齐。"""
    if spec.mode == "dsl":
        entry = evaluate_rule(df, spec.entry_rule)
        exit_ = evaluate_rule(df, spec.exit_rule)
        signals = pd.Series(HOLD, index=df.index)
        signals[exit_] = SELL
        signals[entry] = BUY  # 同一根K线entry/exit都触发时，以entry为准
        return signals

    if spec.mode == "code":
        from quant_strategy.strategy.codegen import load_validated_function

        func = load_validated_function(spec.code)
        signals = func(df.copy())
        if not isinstance(signals, pd.Series):
            signals = pd.Series(signals, index=df.index)
        return signals.reindex(df.index).fillna(HOLD)

    raise ValueError(f"未知策略模式：{spec.mode}")
