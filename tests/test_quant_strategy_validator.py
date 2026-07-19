"""Unit tests for quant_strategy.strategy.validator — AST whitelist security checks."""
import pytest

from quant_strategy.strategy.validator import CodeValidationError, validate_code

VALID_CODE = """
def generate_signals(df):
    ma5 = df["close"].rolling(5).mean()
    ma20 = df["close"].rolling(20).mean()
    signals = []
    for i in range(len(df)):
        if i == 0:
            signals.append("HOLD")
        elif ma5.iloc[i] > ma20.iloc[i]:
            signals.append("BUY")
        else:
            signals.append("HOLD")
    return pd.Series(signals, index=df.index)
"""


def test_valid_code_passes():
    validate_code(VALID_CODE)


@pytest.mark.parametrize("bad_code", [
    'import os\ndef generate_signals(df):\n    return df',
    'from os import path\ndef generate_signals(df):\n    return df',
    'def generate_signals(df):\n    eval("1+1")\n    return df',
    'def generate_signals(df):\n    exec("x=1")\n    return df',
    'def generate_signals(df):\n    open("/etc/passwd")\n    return df',
    'def generate_signals(df):\n    return df.__class__',
    'def generate_signals(df):\n    return __import__("os")',
    'def generate_signals(df):\n    global x\n    return df',
    'class Foo:\n    pass\ndef generate_signals(df):\n    return df',
    'def generate_signals(df):\n    try:\n        return df\n    except Exception:\n        return df',
])
def test_dangerous_code_is_rejected(bad_code):
    with pytest.raises(CodeValidationError):
        validate_code(bad_code)


def test_missing_required_function_is_rejected():
    with pytest.raises(CodeValidationError):
        validate_code("def some_other_func(df):\n    return df")


def test_syntax_error_is_rejected():
    with pytest.raises(CodeValidationError):
        validate_code("def generate_signals(df:\n    return df")
