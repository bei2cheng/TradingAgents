# -*- coding: utf-8 -*-
"""生成 Markdown 回测报告：参数摘要、指标汇总表、权益曲线、逐笔交易明细。"""
import os

from quant_strategy.backtest.metrics import compute_metrics
from quant_strategy.config import STRATEGIES_DIR


def _equity_curve_chart(result, out_path: str) -> str | None:
    """尝试用 matplotlib 画权益曲线 PNG，失败（未安装等）则返回 None。"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    fig, ax = plt.subplots(figsize=(10, 5))
    equity = result.equity_curve["equity"]
    ax.plot(equity.index, equity.values, label="策略净值")
    if result.benchmark_curve is not None and not result.benchmark_curve.empty:
        ax.plot(result.benchmark_curve.index, result.benchmark_curve["close"], label="基准净值", linestyle="--")
    ax.set_xlabel("日期")
    ax.set_ylabel("权益")
    ax.legend()
    ax.set_title("回测权益曲线")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def _equity_curve_ascii(result, width: int = 60, height: int = 12) -> str:
    equity = result.equity_curve["equity"]
    if equity.empty:
        return "(无数据)"
    sampled = equity.iloc[:: max(1, len(equity) // width)] if len(equity) > width else equity
    lo, hi = sampled.min(), sampled.max()
    span = hi - lo if hi > lo else 1.0
    lines = []
    for val in sampled:
        level = int((val - lo) / span * (height - 1))
        lines.append("#" * (level + 1))
    rows = []
    for h in range(height - 1, -1, -1):
        row = "".join("#" if len(l) > h else " " for l in lines)
        rows.append(row)
    chart = "\n".join(rows)
    return f"```\n{chart}\n(纵轴: {lo:.2f} ~ {hi:.2f})\n```"


def generate_report(
    result,
    spec,
    start_date: str,
    end_date: str,
    output_path: str | None = None,
) -> str:
    """生成 Markdown 回测报告，返回报告文本。若指定 output_path 会同时落盘。"""
    metrics = compute_metrics(result)
    metrics_dict = metrics.to_dict()

    lines = [
        f"# 回测报告：{spec.name}",
        "",
        "## 参数摘要",
        "",
        f"- 策略描述：{spec.description or '(无)'}",
        f"- 策略模式：{spec.mode}",
        f"- 股票池：{', '.join(result.ticker_codes)}",
        f"- 回测区间：{start_date} ~ {end_date}",
        f"- 初始资金：{result.initial_cash:,.2f}",
        f"- 期末资金（现金）：{result.final_cash:,.2f}",
        f"- 期末总权益：{result.final_equity:,.2f}",
        "",
        "## 指标汇总",
        "",
        "| 指标 | 数值 |",
        "| --- | --- |",
    ]
    for k, v in metrics_dict.items():
        lines.append(f"| {k} | {v} |")

    lines += ["", "## 权益曲线", ""]
    chart_path = None
    if output_path:
        chart_path = os.path.splitext(output_path)[0] + "_equity.png"
        chart_path = _equity_curve_chart(result, chart_path)
    if chart_path:
        lines.append(f"![权益曲线]({os.path.basename(chart_path)})")
    else:
        lines.append(_equity_curve_ascii(result))

    lines += ["", "## 逐笔交易明细", "", "| 日期 | 股票 | 方向 | 数量 | 价格 | 手续费 | 印花税 | 盈亏 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for t in result.trades:
        pnl_str = f"{t.pnl:,.2f}" if t.pnl is not None else "-"
        lines.append(
            f"| {t.date} | {t.ticker} | {t.side} | {t.shares} | {t.price:.2f} | "
            f"{t.commission:.2f} | {t.stamp_tax:.2f} | {pnl_str} |"
        )

    report_text = "\n".join(lines) + "\n"

    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report_text)

    return report_text


def default_report_path(strategy_name: str, start_date: str, end_date: str) -> str:
    reports_dir = os.path.join(STRATEGIES_DIR, "reports")
    filename = f"{strategy_name}_{start_date}_{end_date}.md".replace(":", "")
    return os.path.join(reports_dir, filename)
