# -*- coding: utf-8 -*-
"""解析 reports/analyze_stock.py 生成的 analysis_report_*.md，提取交易决策。"""
import glob
import os
import re
from dataclasses import dataclass

POSITION_LABELS = ("空仓", "重仓", "中仓", "轻仓")
ACTION_RE = re.compile(r"操作方向[：:]\s*\**\s*(BUY|SELL|HOLD)", re.IGNORECASE)
POSITION_RE = re.compile(r"建议仓位[：:]\s*\**\s*([^\n*]+)")
PRICE_RANGE_RE = re.compile(r"建议操作价区[：:]\s*\**\s*([^\n]*)")
STOP_LOSS_RE = re.compile(r"止损位[：:]\s*\**\s*([^\n]*)")
RATING_RE = re.compile(r"评级[：:]\s*\**\s*([^\n*]+)")
SCORE_RE = re.compile(r"评分[：:]\s*\**\s*([\d.]+\s*/\s*10)")


@dataclass
class TradeDecision:
    ticker: str
    action: str | None  # "BUY" / "SELL" / "HOLD" / None（无法解析）
    position_label: str | None  # 重仓/中仓/轻仓/空仓 / None
    target_weight: float | None  # 占总资产的目标买入比例
    rating: str | None
    score: str | None
    raw_price_text: str | None
    raw_stop_loss_text: str | None
    report_path: str
    warning: str | None = None

    @property
    def is_actionable(self) -> bool:
        return self.action in ("BUY", "SELL") and self.target_weight is not None


def _extract_section(text: str, heading: str) -> str | None:
    """截取从指定 "## heading" 到下一个 "## " 之间的文本块。"""
    pattern = re.compile(rf"##\s*{re.escape(heading)}\s*\n(.*?)(?=\n##\s|\Z)", re.DOTALL)
    m = pattern.search(text)
    return m.group(1) if m else None


def find_latest_report(reports_base: str, ticker: str, date: str | None = None) -> str | None:
    """定位 reports/{TICKER}_{DATE}/analysis_report_{DATE}.md。

    ticker 形如 "603690.SH"。若未指定 date，取该股票目录中日期最新的一份报告。
    """
    if date:
        candidate = os.path.join(reports_base, f"{ticker}_{date}", f"analysis_report_{date}.md")
        return candidate if os.path.isfile(candidate) else None

    pattern = os.path.join(reports_base, f"{ticker}_*", "analysis_report_*.md")
    matches = sorted(glob.glob(pattern))
    return matches[-1] if matches else None


def parse_report(ticker: str, report_path: str, config) -> TradeDecision:
    with open(report_path, encoding="utf-8") as f:
        text = f.read()

    section = _extract_section(text, "交易决策") or text

    action_m = ACTION_RE.search(section)
    action = action_m.group(1).upper() if action_m else None

    position_label = None
    position_m = POSITION_RE.search(section)
    if position_m:
        position_text = position_m.group(1)
        for label in POSITION_LABELS:
            if label in position_text:
                position_label = label
                break

    target_weight = (
        config.position_weight_for_label(position_label) if position_label else None
    )

    price_m = PRICE_RANGE_RE.search(section)
    stop_loss_m = STOP_LOSS_RE.search(section)
    rating_m = RATING_RE.search(text)
    score_m = SCORE_RE.search(text)

    warning = None
    if action is None:
        warning = f"未能从报告中解析出操作方向（操作方向）：{report_path}"
    elif position_label is None:
        warning = f"未能从报告中解析出建议仓位档位：{report_path}"

    return TradeDecision(
        ticker=ticker,
        action=action,
        position_label=position_label,
        target_weight=target_weight,
        rating=rating_m.group(1).strip() if rating_m else None,
        score=score_m.group(1).strip() if score_m else None,
        raw_price_text=price_m.group(1).strip() if price_m else None,
        raw_stop_loss_text=stop_loss_m.group(1).strip() if stop_loss_m else None,
        report_path=report_path,
        warning=warning,
    )


def load_decisions(tickers, config, date: str | None = None) -> list[TradeDecision]:
    """批量加载交易决策；找不到报告或解析失败的股票会带 warning，绝不臆测方向。"""
    decisions = []
    for ticker in tickers:
        report_path = find_latest_report(config.reports_base, ticker, date)
        if report_path is None:
            decisions.append(
                TradeDecision(
                    ticker=ticker,
                    action=None,
                    position_label=None,
                    target_weight=None,
                    rating=None,
                    score=None,
                    raw_price_text=None,
                    raw_stop_loss_text=None,
                    report_path="",
                    warning=f"未找到 {ticker} 的分析报告（date={date or '最新'}）",
                )
            )
            continue
        decisions.append(parse_report(ticker, report_path, config))
    return decisions
