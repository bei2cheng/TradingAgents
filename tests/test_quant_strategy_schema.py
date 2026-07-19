"""Unit tests for quant_strategy.strategy.schema — DSL construction and JSON round-tripping."""
import pytest

from quant_strategy.strategy.schema import Condition, DslError, IndicatorRef, Rule, StrategySpec


def test_indicator_ref_rejects_unknown_name():
    with pytest.raises(DslError):
        IndicatorRef(name="not_a_real_indicator")


def test_indicator_ref_key_includes_params():
    ref = IndicatorRef(name="ma", params={"window": 20})
    assert ref.key() == "ma_window20"
    assert IndicatorRef(name="close").key() == "close"


def test_condition_rejects_unknown_comparator():
    with pytest.raises(DslError):
        Condition(left=IndicatorRef(name="close"), comparator="between", right=1.0)


def test_rule_leaf_requires_condition():
    with pytest.raises(DslError):
        Rule(op="leaf")


def test_rule_and_or_requires_children():
    with pytest.raises(DslError):
        Rule(op="and", children=[])


def test_strategy_spec_dsl_mode_requires_a_rule():
    with pytest.raises(DslError):
        StrategySpec(name="empty", description="", mode="dsl")


def test_strategy_spec_code_mode_requires_code():
    with pytest.raises(DslError):
        StrategySpec(name="empty", description="", mode="code")


def test_strategy_spec_round_trips_through_dict():
    entry = Rule.leaf(Condition(
        left=IndicatorRef(name="ma", params={"window": 5}),
        comparator="cross_above",
        right=IndicatorRef(name="ma", params={"window": 20}),
    ))
    exit_rule = Rule(op="not", children=[entry])
    spec = StrategySpec(name="ma_cross", description="MA5上穿MA20买入", mode="dsl",
                         entry_rule=entry, exit_rule=exit_rule)

    restored = StrategySpec.from_dict(spec.to_dict())

    assert restored.name == spec.name
    assert restored.entry_rule.condition.left.key() == "ma_window5"
    assert restored.exit_rule.op == "not"
    assert restored.exit_rule.children[0].condition.comparator == "cross_above"


def test_strategy_spec_save_and_load(tmp_path):
    entry = Rule.leaf(Condition(left=IndicatorRef(name="rsi", params={"window": 14}),
                                 comparator="lt", right=30.0))
    spec = StrategySpec(name="rsi_oversold", description="RSI<30买入", mode="dsl", entry_rule=entry)

    path = tmp_path / "rsi_oversold.json"
    spec.save(str(path))
    loaded = StrategySpec.load(str(path))

    assert loaded.name == "rsi_oversold"
    assert loaded.entry_rule.condition.right == 30.0
