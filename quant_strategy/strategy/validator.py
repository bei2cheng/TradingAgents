# -*- coding: utf-8 -*-
"""AST 白名单校验：codegen 生成的 Python 代码必须先过此校验才允许 exec。"""
import ast

REQUIRED_FUNC_NAME = "generate_signals"

_ALLOWED_NODES = (
    ast.Module, ast.FunctionDef, ast.Return, ast.arguments, ast.arg,
    ast.Load, ast.Store, ast.Del,
    ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Expr,
    ast.If, ast.For, ast.While, ast.Break, ast.Continue, ast.Pass,
    ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.Compare, ast.Call,
    ast.IfExp, ast.Lambda,
    ast.List, ast.Tuple, ast.Dict, ast.Set,
    ast.Subscript, ast.Slice, ast.Index,
    ast.Name, ast.Constant, ast.Attribute,
    ast.And, ast.Or, ast.Not, ast.Invert, ast.UAdd, ast.USub,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.BitAnd, ast.BitOr, ast.BitXor,  # pandas 向量化布尔运算依赖 &/|/^（非位运算安全风险）
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.In, ast.NotIn, ast.Is, ast.IsNot,
    ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp, ast.comprehension,
    ast.keyword, ast.Starred,
)

_FORBIDDEN_NAMES = {
    "eval", "exec", "compile", "open", "__import__", "input",
    "globals", "locals", "vars", "getattr", "setattr", "delattr",
    "exit", "quit", "help", "breakpoint", "memoryview",
}

_FORBIDDEN_MODULES = {"os", "sys", "subprocess", "socket", "shutil", "importlib", "ctypes", "io"}


class CodeValidationError(ValueError):
    pass


def validate_code(code: str) -> ast.Module:
    """静态校验 codegen 生成的代码，通过则返回解析出的 AST；否则抛 CodeValidationError。"""
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as e:
        raise CodeValidationError(f"代码语法错误：{e}") from e

    has_target_func = False

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise CodeValidationError("禁止 import 语句")
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            raise CodeValidationError("禁止 global/nonlocal 语句")
        if isinstance(node, (ast.ClassDef, ast.AsyncFunctionDef, ast.With, ast.AsyncWith, ast.Try)):
            raise CodeValidationError(f"禁止使用 {type(node).__name__}")
        if not isinstance(node, _ALLOWED_NODES):
            raise CodeValidationError(f"不允许的语法节点：{type(node).__name__}")

        if isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
            raise CodeValidationError(f"禁止引用名称：{node.id}")
        if isinstance(node, ast.Name) and node.id in _FORBIDDEN_MODULES:
            raise CodeValidationError(f"禁止引用模块名：{node.id}")

        if isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                raise CodeValidationError(f"禁止访问 dunder 属性：{node.attr}")

        if isinstance(node, ast.FunctionDef):
            if node.name == REQUIRED_FUNC_NAME:
                has_target_func = True

    if not has_target_func:
        raise CodeValidationError(f"代码必须定义函数 {REQUIRED_FUNC_NAME}(df)")

    return tree
