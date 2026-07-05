# -*- coding: utf-8 -*-
"""QMT 执行程序配置：全部可通过环境变量 / .env 覆盖。"""
import importlib.util
import os
from dataclasses import dataclass, field, replace

from dotenv import load_dotenv

load_dotenv()

REPORTS_BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "reports")
REPORTS_BASE = os.path.normpath(REPORTS_BASE)


def _load_stock_list():
    """从 reports/analyze_stock.py 导入 STOCK_LIST，作为交易白名单的唯一数据源。"""
    path = os.path.join(REPORTS_BASE, "analyze_stock.py")
    spec = importlib.util.spec_from_file_location("_analyze_stock_config_only", path)
    module = importlib.util.module_from_spec(spec)
    # analyze_stock.py 顶层会做网络请求/客户端初始化，这里只取 STOCK_LIST 常量，
    # 因此不执行 spec.loader.exec_module，改用 AST 静态解析，避免副作用。
    import ast

    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "STOCK_LIST" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise RuntimeError(f"未能在 {path} 中找到 STOCK_LIST 定义")


def _to_ticker(code: str, market: str) -> str:
    suffix = "SH" if market.lower() == "sh" else "SZ"
    return f"{code}.{suffix}"


def _env_float(name: str, default: float) -> float:
    val = os.getenv(name)
    return float(val) if val not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val not in (None, "") else default


@dataclass(frozen=True)
class QmtConfig:
    # QMT 客户端安装路径
    site_packages_path: str = os.getenv(
        "QMT_SITE_PACKAGES_PATH", r"D:\国金证券QMT交易端\bin.x64\Lib\site-packages"
    )
    sim_userdata_path: str = os.getenv(
        "QMT_SIM_USERDATA_PATH", os.getenv("QMT_USERDATA_PATH", r"D:\国金证券QMT交易端\userdata_mini")
    )
    live_userdata_path: str = os.getenv(
        "QMT_LIVE_USERDATA_PATH", os.getenv("QMT_USERDATA_PATH", r"D:\国金证券QMT交易端\userdata_mini")
    )
    sim_account_id: str = os.getenv("QMT_SIM_ACCOUNT_ID", "")
    live_account_id: str = os.getenv("QMT_LIVE_ACCOUNT_ID", "")
    account_type: str = os.getenv("QMT_ACCOUNT_TYPE", "STOCK")

    # 仓位档位 -> 目标买入比例（占总资产）
    weight_heavy: float = _env_float("QMT_WEIGHT_HEAVY", 0.35)
    weight_medium: float = _env_float("QMT_WEIGHT_MEDIUM", 0.25)
    weight_light: float = _env_float("QMT_WEIGHT_LIGHT", 0.15)
    weight_empty: float = _env_float("QMT_WEIGHT_EMPTY", 0.0)

    # 风控上限
    max_single_stock_pct: float = _env_float("QMT_MAX_SINGLE_STOCK_PCT", 0.20)
    max_total_position_pct: float = _env_float("QMT_MAX_TOTAL_POSITION_PCT", 0.80)

    # 下单参数
    lot_size: int = _env_int("QMT_LOT_SIZE", 100)
    slippage_pct: float = _env_float("QMT_SLIPPAGE_PCT", 0.005)
    min_order_notional: float = _env_float("QMT_MIN_ORDER_NOTIONAL", 1000.0)

    reports_base: str = REPORTS_BASE
    stock_whitelist: tuple = field(default_factory=tuple)

    def position_weight_for_label(self, label: str) -> float:
        mapping = {
            "空仓": self.weight_empty,
            "重仓": self.weight_heavy,
            "中仓": self.weight_medium,
            "轻仓": self.weight_light,
        }
        return mapping.get(label, self.weight_empty)

    def userdata_path(self, mode: str) -> str:
        return self.sim_userdata_path if mode == "sim" else self.live_userdata_path

    def account_id(self, mode: str) -> str:
        account_id = self.sim_account_id if mode == "sim" else self.live_account_id
        if not account_id:
            env_name = "QMT_SIM_ACCOUNT_ID" if mode == "sim" else "QMT_LIVE_ACCOUNT_ID"
            raise RuntimeError(
                f"未配置 {env_name}，请在 .env 中设置 {mode} 模式对应的 QMT 资金账号 ID"
            )
        return account_id


def load_config() -> QmtConfig:
    cfg = QmtConfig()
    whitelist = tuple(_to_ticker(code, market) for code, market in _load_stock_list())
    return replace(cfg, stock_whitelist=whitelist)
