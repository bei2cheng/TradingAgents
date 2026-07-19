# -*- coding: utf-8 -*-
"""DSL 覆盖不了时的兜底：对通过 validator.py 校验的 LLM 生成代码，在受限命名空间中 exec 并提取 generate_signals 函数。"""
import numpy as np
import pandas as pd

from quant_strategy.strategy.validator import REQUIRED_FUNC_NAME, validate_code

_SAFE_BUILTINS = {
    "len": len, "range": range, "min": min, "max": max, "sum": sum,
    "abs": abs, "round": round, "enumerate": enumerate, "zip": zip,
    "sorted": sorted, "list": list, "dict": dict, "set": set, "tuple": tuple,
    "str": str, "int": int, "float": float, "bool": bool,
    "isinstance": isinstance, "True": True, "False": False, "None": None,
}


def load_validated_function(code: str):
    """校验并加载 codegen 代码，返回 generate_signals(df) -> pd.Series[BUY|SELL|HOLD] 可调用对象。"""
    validate_code(code)

    namespace = {"__builtins__": _SAFE_BUILTINS, "pd": pd, "np": np}
    exec(compile(code, "<quant_strategy_codegen>", "exec"), namespace)

    func = namespace.get(REQUIRED_FUNC_NAME)
    if not callable(func):
        raise ValueError(f"代码校验通过但未找到可调用的 {REQUIRED_FUNC_NAME}")
    return func
