"""Unit tests for quant_strategy.strategy.compiler — mocks the LLM call, never touches the network."""
import pytest

import quant_strategy.strategy.compiler as compiler
from quant_strategy.strategy.compiler import DslUnsupportedError, compile_text_to_strategy
from quant_strategy.strategy.validator import REQUIRED_FUNC_NAME

VALID_DSL_JSON = """
{
  "entry_rule": {"op": "leaf", "condition": {
      "left": {"name": "ma", "params": {"window": 5}},
      "comparator": "cross_above",
      "right": {"name": "ma", "params": {"window": 20}}
  }},
  "exit_rule": {"op": "leaf", "condition": {
      "left": {"name": "ma", "params": {"window": 5}},
      "comparator": "cross_below",
      "right": {"name": "ma", "params": {"window": 20}}
  }}
}
"""

UNSUPPORTED_JSON = '{"unsupported": true}'

SELF_COMPARISON_JSON = """
{
  "entry_rule": {"op": "and", "children": [
      {"op": "leaf", "condition": {
          "left": {"name": "volume", "params": {}},
          "comparator": "gt",
          "right": {"name": "volume", "params": {}}
      }}
  ]},
  "exit_rule": null
}
"""

VALID_CODEGEN_CODE = f"""```python
def {REQUIRED_FUNC_NAME}(df):
    ma5 = df["close"].rolling(5).mean()
    ma20 = df["close"].rolling(20).mean()
    signals = []
    for i in range(len(df)):
        signals.append("BUY" if ma5.iloc[i] > ma20.iloc[i] else "HOLD")
    return pd.Series(signals, index=df.index)
```"""

DANGEROUS_CODEGEN_CODE = f"""```python
import os
def {REQUIRED_FUNC_NAME}(df):
    return df
```"""


def _patch_chat(monkeypatch, dsl_response, codegen_response=None):
    def fake_chat(system_prompt, user_text):
        if "generate_signals" in system_prompt and "严格要求" in system_prompt:
            return codegen_response
        return dsl_response

    monkeypatch.setattr(compiler, "_chat", fake_chat)


def test_compile_text_to_strategy_uses_dsl_when_llm_returns_valid_rules(monkeypatch):
    _patch_chat(monkeypatch, dsl_response=VALID_DSL_JSON)

    spec = compile_text_to_strategy("MA5上穿MA20买入，下穿卖出", "ma_cross")

    assert spec.mode == "dsl"
    assert spec.entry_rule.condition.comparator == "cross_above"
    assert spec.exit_rule.condition.comparator == "cross_below"


def test_compile_text_to_strategy_falls_back_to_codegen_when_dsl_unsupported(monkeypatch):
    _patch_chat(monkeypatch, dsl_response=UNSUPPORTED_JSON, codegen_response=VALID_CODEGEN_CODE)

    spec = compile_text_to_strategy("根据最新财报营收增速买入", "earnings_growth")

    assert spec.mode == "code"
    assert REQUIRED_FUNC_NAME in spec.code


def test_compile_text_to_strategy_falls_back_to_codegen_on_malformed_dsl_json(monkeypatch):
    _patch_chat(monkeypatch, dsl_response="not valid json at all", codegen_response=VALID_CODEGEN_CODE)

    spec = compile_text_to_strategy("一些奇怪的描述", "weird")

    assert spec.mode == "code"


def test_compile_text_to_strategy_falls_back_to_codegen_on_self_comparison_dsl(monkeypatch):
    """Regression test: an LLM DSL response comparing an indicator to itself (e.g. volume > volume,
    seen in practice when the description needs pattern logic the DSL can't express) must NOT be
    accepted as a valid strategy — it should fall back to codegen instead of silently producing a
    rule that can never trigger."""
    _patch_chat(monkeypatch, dsl_response=SELF_COMPARISON_JSON, codegen_response=VALID_CODEGEN_CODE)

    spec = compile_text_to_strategy("堆量多连阳", "bot_vol_rally")

    assert spec.mode == "code"


def test_compile_text_to_strategy_raises_when_both_paths_fail(monkeypatch):
    _patch_chat(monkeypatch, dsl_response=UNSUPPORTED_JSON, codegen_response=DANGEROUS_CODEGEN_CODE)

    with pytest.raises(DslUnsupportedError):
        compile_text_to_strategy("根据内幕消息买入", "insider_tip")
