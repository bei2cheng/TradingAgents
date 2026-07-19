# -*- coding: utf-8 -*-
"""策略 DSL 数据模型：IndicatorRef / Condition / Rule / StrategySpec，均可 JSON 序列化往返。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

INDICATORS = (
    "close", "open", "high", "low", "volume",
    "ma", "ema", "macd_dif", "macd_dea", "macd_hist",
    "rsi", "boll_upper", "boll_mid", "boll_lower",
    "volume_ratio", "highest", "lowest",
)

COMPARATORS = ("gt", "gte", "lt", "lte", "cross_above", "cross_below")


class DslError(ValueError):
    """DSL 结构不合法（未知指标/比较符/字段缺失等）。"""


@dataclass
class IndicatorRef:
    """指标引用，例如 ma(20) -> IndicatorRef(name="ma", params={"window": 20})。"""

    name: str
    params: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.name not in INDICATORS:
            raise DslError(f"未知指标：{self.name}，可选：{INDICATORS}")

    def key(self) -> str:
        if not self.params:
            return self.name
        parts = "_".join(f"{k}{v}" for k, v in sorted(self.params.items()))
        return f"{self.name}_{parts}"

    def to_dict(self) -> dict:
        return {"name": self.name, "params": self.params}

    @classmethod
    def from_dict(cls, d: dict) -> "IndicatorRef":
        return cls(name=d["name"], params=dict(d.get("params") or {}))


@dataclass
class Condition:
    """left <comparator> right。right 既可以是另一个指标引用，也可以是常数阈值。"""

    left: IndicatorRef
    comparator: str
    right: IndicatorRef | float

    def __post_init__(self):
        if self.comparator not in COMPARATORS:
            raise DslError(f"未知比较符：{self.comparator}，可选：{COMPARATORS}")
        if isinstance(self.right, IndicatorRef) and self.left.key() == self.right.key():
            raise DslError(f"条件两侧指标相同（{self.left.key()}），无法构成有效比较")

    def describe(self) -> str:
        right_desc = self.right.key() if isinstance(self.right, IndicatorRef) else str(self.right)
        return f"{self.left.key()} {self.comparator} {right_desc}"

    def to_dict(self) -> dict:
        return {
            "left": self.left.to_dict(),
            "comparator": self.comparator,
            "right": self.right.to_dict() if isinstance(self.right, IndicatorRef) else self.right,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Condition":
        right = d["right"]
        right = IndicatorRef.from_dict(right) if isinstance(right, dict) else float(right)
        return cls(left=IndicatorRef.from_dict(d["left"]), comparator=d["comparator"], right=right)


@dataclass
class Rule:
    """条件树：op="leaf" 时使用 condition；op in ("and","or","not") 时使用 children。"""

    op: str
    children: list["Rule"] = field(default_factory=list)
    condition: Condition | None = None

    def __post_init__(self):
        if self.op not in ("and", "or", "not", "leaf"):
            raise DslError(f"未知规则组合符：{self.op}，可选：and/or/not/leaf")
        if self.op == "leaf" and self.condition is None:
            raise DslError("leaf 规则必须携带 condition")
        if self.op != "leaf" and not self.children:
            raise DslError(f"{self.op} 规则至少需要一个子规则")

    def describe(self) -> str:
        if self.op == "leaf":
            return self.condition.describe()
        joiner = {"and": " 且 ", "or": " 或 ", "not": " 非 "}[self.op]
        parts = [c.describe() for c in self.children]
        return f"({joiner.join(parts)})" if self.op != "not" else f"非({parts[0]})"

    def to_dict(self) -> dict:
        d = {"op": self.op}
        if self.op == "leaf":
            d["condition"] = self.condition.to_dict()
        else:
            d["children"] = [c.to_dict() for c in self.children]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Rule":
        if d["op"] == "leaf":
            return cls(op="leaf", condition=Condition.from_dict(d["condition"]))
        return cls(op=d["op"], children=[cls.from_dict(c) for c in d.get("children", [])])

    @classmethod
    def leaf(cls, condition: Condition) -> "Rule":
        return cls(op="leaf", condition=condition)


@dataclass
class StrategySpec:
    """一个可执行策略：DSL 模式（entry_rule/exit_rule）或 codegen 模式（code）二选一。"""

    name: str
    description: str
    mode: str = "dsl"  # "dsl" | "code"
    entry_rule: Rule | None = None
    exit_rule: Rule | None = None
    code: str | None = None
    params: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.mode not in ("dsl", "code"):
            raise DslError(f"未知策略模式：{self.mode}，可选：dsl/code")
        if self.mode == "dsl" and self.entry_rule is None and self.exit_rule is None:
            raise DslError("dsl 模式下 entry_rule 和 exit_rule 不能同时为空")
        if self.mode == "code" and not self.code:
            raise DslError("code 模式下必须提供 code")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "mode": self.mode,
            "entry_rule": self.entry_rule.to_dict() if self.entry_rule else None,
            "exit_rule": self.exit_rule.to_dict() if self.exit_rule else None,
            "code": self.code,
            "params": self.params,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StrategySpec":
        return cls(
            name=d["name"],
            description=d.get("description", ""),
            mode=d.get("mode", "dsl"),
            entry_rule=Rule.from_dict(d["entry_rule"]) if d.get("entry_rule") else None,
            exit_rule=Rule.from_dict(d["exit_rule"]) if d.get("exit_rule") else None,
            code=d.get("code"),
            params=dict(d.get("params") or {}),
        )

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "StrategySpec":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
