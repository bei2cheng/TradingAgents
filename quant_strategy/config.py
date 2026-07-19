# -*- coding: utf-8 -*-
"""quant_strategy 全局配置：A股交易规则常量 + 回测默认参数 + LLM 接入配置，均可用环境变量覆盖。"""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_CACHE_DIR = os.path.join(REPO_ROOT, "data_cache")
STRATEGIES_DIR = os.path.join(REPO_ROOT, "strategies")


def _env_float(name: str, default: float) -> float:
    val = os.getenv(name)
    return float(val) if val not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val not in (None, "") else default


@dataclass(frozen=True)
class AShareRules:
    """A股交易规则常量（回测引擎按此模拟成交约束）。"""

    lot_size: int = _env_int("QS_LOT_SIZE", 100)  # 买入按整手（100股）取整
    price_limit_pct: float = _env_float("QS_PRICE_LIMIT_PCT", 0.10)  # 普通股涨跌停幅度
    st_price_limit_pct: float = _env_float("QS_ST_PRICE_LIMIT_PCT", 0.05)  # ST股涨跌停幅度
    t_plus: int = 1  # T+1：当日买入次日才可卖出


@dataclass(frozen=True)
class BacktestDefaults:
    initial_cash: float = _env_float("QS_BACKTEST_INITIAL_CASH", 1_000_000.0)
    commission_rate: float = _env_float("QS_COMMISSION_RATE", 0.0003)  # 佣金费率（双边）
    min_commission: float = _env_float("QS_MIN_COMMISSION", 5.0)  # 单笔最低佣金
    stamp_tax_rate: float = _env_float("QS_STAMP_TAX_RATE", 0.001)  # 印花税（仅卖出）
    slippage_pct: float = _env_float("QS_SLIPPAGE_PCT", 0.001)  # 成交滑点
    position_pct_per_trade: float = _env_float("QS_POSITION_PCT_PER_TRADE", 0.0)  # 0=按股票数等权
    benchmark_code: str = os.getenv("QS_BENCHMARK_CODE", "000300.SH")  # 沪深300，用于计算超额收益


@dataclass(frozen=True)
class LlmConfig:
    """文字描述 -> DSL/代码所用的 LLM 接入配置，默认走 DeepSeek（与 reports/analyze_stock.py 一致）。"""

    api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    base_url: str = os.getenv("QS_LLM_BASE_URL", "https://api.deepseek.com")
    model: str = os.getenv("QS_LLM_MODEL", "deepseek-chat")


AShare = AShareRules()
BacktestDefault = BacktestDefaults()
Llm = LlmConfig()

os.makedirs(DATA_CACHE_DIR, exist_ok=True)
os.makedirs(STRATEGIES_DIR, exist_ok=True)
