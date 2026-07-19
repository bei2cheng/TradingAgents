# -*- coding: utf-8 -*-
"""文本 -> DSL：调用 LLM 把策略文字描述映射成 StrategySpec；DSL 覆盖不了时降级到 codegen 兜底。"""
import json
import re

from quant_strategy.config import Llm
from quant_strategy.strategy.codegen import REQUIRED_FUNC_NAME
from quant_strategy.strategy.schema import COMPARATORS, INDICATORS, DslError, Rule, StrategySpec
from quant_strategy.strategy.validator import CodeValidationError, validate_code


class DslUnsupportedError(RuntimeError):
    """DSL 和 codegen 两条路径都无法把文字描述转成可执行策略时抛出。"""


def _client():
    from openai import OpenAI
    if not Llm.api_key:
        raise RuntimeError("未配置 LLM API Key（DEEPSEEK_API_KEY），无法调用文本转策略")
    return OpenAI(api_key=Llm.api_key, base_url=Llm.base_url)


def _extract_json(text: str) -> dict:
    text = text.strip()
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if match:
        text = match.group(1).strip()
    return json.loads(text)


def _extract_code(text: str) -> str:
    text = text.strip()
    match = re.search(r"```(?:python)?\s*(.*?)```", text, re.DOTALL)
    return match.group(1).strip() if match else text


_DSL_SYSTEM_PROMPT = f"""你是量化策略助手，负责把用户的中文策略描述转换成结构化 JSON 规则，用于A股择时策略。

只允许使用以下指标名（IndicatorRef.name）：{list(INDICATORS)}
指标可带参数 params，例如 {{"name": "ma", "params": {{"window": 20}}}} 表示20日均线；
{{"name": "rsi", "params": {{"window": 14}}}} 表示14日RSI；close/open/high/low/volume 不需要 params。

只允许使用以下比较符（Condition.comparator）：{list(COMPARATORS)}
cross_above/cross_below 表示左指标上穿/下穿右指标（或右侧常数阈值）。

Condition 结构：{{"left": IndicatorRef, "comparator": "...", "right": IndicatorRef 或 数字}}
Rule 结构（递归）：
- 叶子条件：{{"op": "leaf", "condition": Condition}}
- 组合：{{"op": "and"|"or", "children": [Rule, ...]}}
- 取反：{{"op": "not", "children": [Rule]}}

请只输出如下 JSON（不要多余文字），entry_rule 为买入触发条件，exit_rule 为卖出触发条件，
如果描述中只提到买入或只提到卖出，另一个可以是 null：
{{"entry_rule": Rule 或 null, "exit_rule": Rule 或 null}}
如果这个描述无法用上述指标/比较符表达（例如涉及财报、新闻、消息面等非技术指标信息），
请只输出：{{"unsupported": true}}
"""

_CODEGEN_SYSTEM_PROMPT = f"""你是量化策略代码生成助手。请把用户的中文策略描述转换成一个 Python 函数：

def {REQUIRED_FUNC_NAME}(df):
    # df 是 pandas DataFrame，index 为交易日期（升序），列包含 open/high/low/close/volume
    # 返回一个与 df.index 对齐的 pandas Series，每个值是 "BUY" / "SELL" / "HOLD" 三者之一
    ...
    return signals

严格要求：
- 只能使用 pandas（变量名 pd）和 numpy（变量名 np），不允许 import 任何模块
- 不允许使用 eval/exec/open/__import__/os/sys 等
- 不允许定义其他函数之外的顶层副作用代码（不打印、不写文件、不访问网络）
- 只输出一个 python 代码块，不要多余解释文字
"""


def _chat(system_prompt: str, user_text: str) -> str:
    client = _client()
    resp = client.chat.completions.create(
        model=Llm.model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        temperature=0,
    )
    return resp.choices[0].message.content


def compile_dsl(text: str, name: str) -> StrategySpec:
    content = _chat(_DSL_SYSTEM_PROMPT, text)
    data = _extract_json(content)
    if data.get("unsupported"):
        raise DslError("LLM 判定该描述无法用现有 DSL 指标/比较符表达")

    entry_rule = Rule.from_dict(data["entry_rule"]) if data.get("entry_rule") else None
    exit_rule = Rule.from_dict(data["exit_rule"]) if data.get("exit_rule") else None
    return StrategySpec(name=name, description=text, mode="dsl", entry_rule=entry_rule, exit_rule=exit_rule)


def compile_codegen(text: str, name: str) -> StrategySpec:
    content = _chat(_CODEGEN_SYSTEM_PROMPT, text)
    code = _extract_code(content)
    validate_code(code)  # 校验失败会抛 CodeValidationError，交由调用方处理
    return StrategySpec(name=name, description=text, mode="code", code=code)


def compile_text_to_strategy(text: str, name: str) -> StrategySpec:
    """先尝试 DSL 规则映射，失败/不可表达时自动降级到 codegen；两者都失败则抛 DslUnsupportedError。"""
    dsl_error = None
    try:
        return compile_dsl(text, name)
    except (DslError, ValueError, KeyError, json.JSONDecodeError) as e:
        dsl_error = e

    try:
        return compile_codegen(text, name)
    except (CodeValidationError, ValueError, json.JSONDecodeError) as e2:
        raise DslUnsupportedError(
            f"无法将策略描述转换为可执行策略：DSL路径失败（{dsl_error}），codegen路径也失败（{e2}）"
        ) from e2
