"""Unit tests for qmt_trading.report_parser — no xtquant/QMT client required."""
import os

from qmt_trading.config import QmtConfig
from qmt_trading.report_parser import parse_report

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SYNTHETIC_BUY_REPORT = """# 000001.SZ（示例公司）投资分析报告

## 交易决策
- **操作方向：BUY**
- **建议仓位：重仓**
- **建议操作价区：** 10.00 ~ 11.00 元
- **止损位：** 9.20 元
- **6个月目标价：** 13.00 ~ 14.00 元

## 关键观察指标
- 无
"""


def _config():
    return QmtConfig(stock_whitelist=("603690.SH", "000001.SZ"))


def test_parse_real_sell_report():
    report_path = os.path.join(
        REPO_ROOT, "reports", "603690.SH_20260704", "analysis_report_20260704.md"
    )
    decision = parse_report("603690.SH", report_path, _config())

    assert decision.action == "SELL"
    assert decision.position_label == "空仓"
    assert decision.target_weight == 0.0
    assert decision.warning is None
    # SELL + 空仓 => 目标权重0，若持仓则清仓；is_actionable 仅代表"可参与仓位计算"
    assert decision.is_actionable


def test_parse_synthetic_buy_report(tmp_path):
    report_path = tmp_path / "analysis_report_synthetic.md"
    report_path.write_text(SYNTHETIC_BUY_REPORT, encoding="utf-8")

    decision = parse_report("000001.SZ", str(report_path), _config())

    assert decision.action == "BUY"
    assert decision.position_label == "重仓"
    assert decision.target_weight == 0.35
    assert decision.warning is None
    assert decision.is_actionable
    assert "9.20" in decision.raw_stop_loss_text


def test_parse_missing_action_sets_warning(tmp_path):
    report_path = tmp_path / "analysis_report_broken.md"
    report_path.write_text("## 交易决策\n没有标准字段\n", encoding="utf-8")

    decision = parse_report("000001.SZ", str(report_path), _config())

    assert decision.action is None
    assert decision.warning is not None
    assert not decision.is_actionable
