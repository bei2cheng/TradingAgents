# -*- coding: utf-8 -*-
"""
TradingAgents 风格 A 股批量分析引擎
- 股票代码在 STOCK_LIST 中配置
- 每只股票生成独立报告目录：reports/{TICKER}.{SUFFIX}_{DATE}/
- 报告文件名带最新分析日期
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import os
from dotenv import load_dotenv
load_dotenv()
import datetime
import json
import warnings
warnings.filterwarnings("ignore")

# ── 在 akshare 导入前注入 UA，修复东方财富反爬 ─────────────────
import requests as _req
from requests import Session as _OrigSession
_EM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.eastmoney.com/",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

import requests.sessions as _req_sessions

class _PatchedSession(_OrigSession):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.headers.update(_EM_HEADERS)

    def request(self, method, url, **kw):
        # 默认 15s 超时，防止 timeout=None 挂死
        if kw.get("timeout") is None:
            kw["timeout"] = 15
        return super().request(method, url, **kw)

_req.Session = _PatchedSession
_req_sessions.Session = _PatchedSession
# ─────────────────────────────────────────────────────────────

import akshare as ak
import baostock as bs
import pandas as pd
import numpy as np
from openai import OpenAI

# ══════════════════════════════════════════════════════════════
#  ★ 配置区：在此修改要分析的股票列表和日期
# ══════════════════════════════════════════════════════════════
# STOCK_LIST = [
#     ("603690", "sh"),   # 至纯科技
#     ("603985", "sh"),   # 恒润股份
#     ("601788", "sh"),   # 光大证券
#     ("002736", "sz"),   # 国信证券
#     ("002945", "sz"),   # 华林证券
#     ("600839", "sh"),   # 四川长虹


#     ("002643", "sz"),   # 万润股份
#     ("300005", "sz"),   # 探路者
#     ("000733", "sz"),   # 振华科技
#     ("300033", "sz"),   # 同花顺
#     ("000066", "sz"),   # 中国长城
#     ("002415", "sz"),   # 海康威视
#     ("301629", "sz"),   # 矽电股份
#     ("300493", "sz"),   # 润欣科技
# ]

STOCK_LIST = [
    ("601788", "sh"),   # 光大证券
    ("300033", "sz"),   # 同花顺
    ("002736", "sz"),   # 国信证券
    # ("002945", "sz"),   # 华林证券
    ("601066", "sh"),   # 中信建投

    ("601600", "sh"),   # 中国铝业
    ("600459", "sh"),   # 贵研铂业
    ("003021", "sz"),   # 兆威机电

    ("300005", "sz"),   # 探路者
    ("000733", "sz"),   # 振华科技
    ("600765", "sh"),   # 中航重机
    ("300428", "sz"),   # 立中集团

    ("600839", "sh"),   # 四川长虹
    ("000066", "sz"),   # 中国长城
    ("002415", "sz"),   # 海康威视
    ("002643", "sz"),   # 万润股份
    ("603985", "sh"),   # 恒润股份
    # ("300493", "sz"),   # 润欣科技
    ("603690", "sh"),   # 至纯科技
    ("301629", "sz"),   # 矽电股份
]

# STOCK_LIST = [
#     ("002643", "sz"),   # 万润股份 
# ]

# 分析日期：默认今天，可手动指定如 "2026-06-30"
ANALYSIS_DATE = datetime.date.today().strftime("%Y-%m-%d")

# DeepSeek API Key
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
# ══════════════════════════════════════════════════════════════

REPORTS_BASE = os.path.dirname(os.path.abspath(__file__))
DATE_TAG = ANALYSIS_DATE.replace("-", "")

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")


def p(msg, flush=True):
    print(msg, flush=flush)


# ──────────────────────────────────────────────────────────────
# 提示词模板
# ──────────────────────────────────────────────────────────────
SYS_FUNDAMENTAL = """你是一位专业的A股基本面分析师。
基于提供的数据，深入分析：
1. 盈利能力（利润率、增速、ROE趋势）
2. 财务健康（负债率、现金流、资本结构）
3. 估值水平（PE/PB是否合理、与行业比较）
4. 竞争优势和商业模式
5. 主要风险因素
用中文结构化报告，不超过600字。"""

SYS_TECHNICAL = """你是一位专业的A股技术分析师。
基于提供的技术指标，深入分析：
1. 趋势判断（主趋势/次趋势）
2. 均线系统信号（多/空头排列、交叉）
3. MACD、RSI信号解读
4. 布林带位置与含义
5. 量价关系分析
6. 关键支撑/压力位
7. 短期（1-2周）和中期（1-2月）展望
用中文结构化报告，不超过600字。"""

SYS_SENTIMENT = """你是一位专业的市场情绪分析师。
基于提供的新闻、资金流向和机构评级，分析：
1. 重要新闻事件及其潜在影响
2. 主力资金行为分析（买入/卖出意图）
3. 机构评级和目标价解读
4. 当前市场情绪定性（乐观/中性/悲观）
5. 短期催化剂和风险事件
用中文结构化报告，不超过600字。"""

SYS_DECISION = """你是资深A股投资决策专家，综合所有分析报告形成最终决策。

必须按以下格式输出：

## 综合评估摘要
（2-3句概括当前状态，点明核心矛盾）

## 多方论据（看涨理由）
- （列举3-5条，具体数据支撑）

## 空方论据（看跌风险）
- （列举3-5条，具体数据支撑）

## 综合评级
- 评级：[强力买入 / 买入 / 持有 / 卖出 / 强力卖出]
- 评分：X/10

## 交易决策
- 操作方向：[BUY / SELL / HOLD]
- 建议仓位：[重仓(>60%) / 中仓(30-60%) / 轻仓(<30%) / 空仓]
- 建议操作价区：X.XX ~ X.XX 元
- 止损位：X.XX 元
- 6个月目标价：X.XX ~ X.XX 元

## 关键观察指标
（列出2-3个后续需重点跟踪的信号）

## 风险提示
（简洁说明主要风险）"""


# ──────────────────────────────────────────────────────────────
# 单只股票分析函数
# ──────────────────────────────────────────────────────────────
def analyze_one(ticker: str, market: str, analysis_date: str) -> dict:
    """分析单只A股，返回包含 report_file、status 的结果字典。"""
    suffix = "SH" if market.lower() == "sh" else "SZ"
    ticker_display = f"{ticker}.{suffix}"
    date_tag = analysis_date.replace("-", "")

    report_dir = os.path.join(REPORTS_BASE, f"{ticker_display}_{date_tag}")
    os.makedirs(report_dir, exist_ok=True)
    result_file = os.path.join(report_dir, f"analysis_report_{date_tag}.md")
    data_file   = os.path.join(report_dir, f"raw_data_{date_tag}.json")

    p("\n" + "=" * 64)
    p(f"  开始分析：{ticker_display}")
    p(f"  分析日期：{analysis_date}")
    p(f"  输出目录：{report_dir}")
    p("=" * 64)

    raw_data = {}

    # ── 1. 基本信息（baostock，独立服务器） ──────────────────
    p("\n[1/8] 获取股票基本信息（baostock）...")
    info_dict = {}
    bs_code = f"{'sh' if suffix == 'SH' else 'sz'}.{ticker}"
    try:
        bs.login()
        rs = bs.query_stock_basic(code=bs_code)
        if rs.error_code == "0" and rs.next():
            row_bs = rs.get_row_data()
            fields = rs.fields
            info_dict = dict(zip(fields, row_bs))
            # 字段映射
            name_map = {
                "code_name": "股票简称", "industry": "行业",
                "ipoDate": "上市时间", "outDate": "退市时间",
                "type": "股票类型", "status": "上市状态",
            }
            info_dict = {name_map.get(k, k): v for k, v in info_dict.items()}
        bs.logout()
        p(f"  公司名称：{info_dict.get('股票简称', 'N/A')}")
        p(f"  所属行业：{info_dict.get('行业', 'N/A')}")
        p(f"  上市日期：{info_dict.get('上市时间', 'N/A')}")
    except Exception as e:
        p(f"  baostock基本信息获取失败: {e}")
        try:
            bs.logout()
        except Exception:
            pass

    # 补充估值信息（akshare spot，容错）
    if not info_dict.get("总市值"):
        try:
            spot = ak.stock_zh_a_spot_em()
            row_s = spot[spot["代码"] == ticker]
            if not row_s.empty:
                r = row_s.iloc[0]
                info_dict.update({
                    "股票简称":    str(r.get("名称", info_dict.get("股票简称", "N/A"))),
                    "总市值":      str(r.get("总市值", "N/A")),
                    "流通市值":    str(r.get("流通市值", "N/A")),
                    "市盈率(TTM)": str(r.get("市盈率-动态", "N/A")),
                    "市净率":      str(r.get("市净率", "N/A")),
                    "换手率":      str(r.get("换手率", "N/A")),
                    "最新价":      str(r.get("最新价", "N/A")),
                })
                p(f"  [补充] 市值：{info_dict['总市值']}  PE：{info_dict['市盈率(TTM)']}")
        except Exception as e2:
            p(f"  估值补充失败（容错跳过）: {e2}")

    raw_data["info"] = {str(k): str(v) for k, v in info_dict.items()}

    # ── 2. 行情数据（baostock，独立服务器） ──────────────────
    p("\n[2/8] 获取近6个月行情数据（baostock）...")
    df = pd.DataFrame()
    price_data_ok = False
    try:
        bs.login()
        start_bs = (datetime.date.today() - datetime.timedelta(days=250)).strftime("%Y-%m-%d")
        end_bs   = analysis_date
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,close,high,low,volume,amount,turn,pctChg",
            start_date=start_bs, end_date=end_bs,
            frequency="d", adjustflag="2",   # 2=前复权
        )
        bs.logout()
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
        if rows:
            df = pd.DataFrame(rows, columns=["日期","开盘","收盘","最高","最低","成交量","成交额","换手率","涨跌幅"])
            for col in ["开盘","收盘","最高","最低","成交量","成交额","换手率","涨跌幅"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df["日期"] = pd.to_datetime(df["日期"])
            df = df.dropna(subset=["收盘"]).sort_values("日期").reset_index(drop=True)
            latest_row = df.iloc[-1]
            p(f"  最新收盘价：{latest_row['收盘']:.2f} 元  涨跌幅：{latest_row['涨跌幅']:.2f}%  "
              f"换手率：{latest_row['换手率']:.2f}%  交易日：{len(df)}")
            price_data_ok = True
        else:
            p("  baostock行情数据为空")
    except Exception as e:
        p(f"  baostock行情数据获取失败: {e}")
        try:
            bs.logout()
        except Exception:
            pass

    # ── 3. 技术指标 ──────────────────────────────────────────
    p("\n[3/8] 计算技术指标...")
    tech_summary = {}
    if price_data_ok and len(df) >= 20:
        close  = df["收盘"]
        volume = df["成交量"]
        lr     = df.iloc[-1]

        ma5  = close.rolling(5).mean().iloc[-1]
        ma10 = close.rolling(10).mean().iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1] if len(df) >= 60 else None

        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        dif   = ema12 - ema26
        dea   = dif.ewm(span=9, adjust=False).mean()
        macd  = (dif - dea) * 2

        delta = close.diff()
        gain  = delta.where(delta > 0, 0).rolling(14).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi   = (100 - 100 / (1 + gain / (loss + 1e-10))).iloc[-1]

        bb_mid   = close.rolling(20).mean()
        bb_std   = close.rolling(20).std()
        bb_upper = (bb_mid + 2 * bb_std).iloc[-1]
        bb_lower = (bb_mid - 2 * bb_std).iloc[-1]
        bb_mid_v = bb_mid.iloc[-1]

        vol_ma5  = volume.rolling(5).mean().iloc[-1]
        vol_ma20 = volume.rolling(20).mean().iloc[-1]
        ret_5d   = (close.iloc[-1] / close.iloc[-6]  - 1) * 100 if len(df) >= 6  else None
        ret_20d  = (close.iloc[-1] / close.iloc[-21] - 1) * 100 if len(df) >= 21 else None

        chg_col = "涨跌幅" if "涨跌幅" in df.columns else "pctChg"
        tech_summary = {
            "latest_close":     float(lr["收盘"]),
            "latest_change_pct": float(lr[chg_col]) if chg_col in lr.index else float("nan"),
            "ma5":  float(ma5),  "ma10": float(ma10),
            "ma20": float(ma20), "ma60": float(ma60) if ma60 is not None else None,
            "dif":  float(dif.iloc[-1]), "dea": float(dea.iloc[-1]),
            "macd": float(macd.iloc[-1]),
            "rsi14": float(rsi),
            "bb_upper": float(bb_upper), "bb_mid": float(bb_mid_v), "bb_lower": float(bb_lower),
            "vol_ma5": float(vol_ma5), "vol_ma20": float(vol_ma20),
            "vol_ratio": float(vol_ma5 / (vol_ma20 + 1e-10)),
            "ret_5d_pct":  float(ret_5d)  if ret_5d  is not None else None,
            "ret_20d_pct": float(ret_20d) if ret_20d is not None else None,
        }
        _ma60s = f"{ma60:.2f}" if ma60 is not None else "N/A"
        _r5s   = f"{ret_5d:.2f}%" if ret_5d is not None else "N/A"
        _r20s  = f"{ret_20d:.2f}%" if ret_20d is not None else "N/A"
        p(f"  价格:{tech_summary['latest_close']:.2f}  MA5:{ma5:.2f}  MA20:{ma20:.2f}  MA60:{_ma60s}")
        p(f"  RSI(14):{rsi:.1f}  MACD柱:{macd.iloc[-1]:.4f}")
        p(f"  布林:[{bb_lower:.2f}~{bb_upper:.2f}] 中轨:{bb_mid_v:.2f}")
        p(f"  量比(5/20日):{vol_ma5/(vol_ma20+1e-10):.2f}  近5日:{_r5s}  近20日:{_r20s}")

    raw_data["tech"] = tech_summary

    # ── 4. 财务数据（emweb.securities.eastmoney.com） ────────
    p("\n[4/8] 获取财务报表...")
    financial_data = {}
    # akshare 财务函数需要 SH/SZ 前缀格式
    ticker_with_prefix = f"{suffix}{ticker}"
    for label, func in [
        ("利润表",    lambda: ak.stock_profit_sheet_by_report_em(symbol=ticker_with_prefix)),
        ("资产负债表", lambda: ak.stock_balance_sheet_by_report_em(symbol=ticker_with_prefix)),
        ("现金流量表", lambda: ak.stock_cash_flow_sheet_by_report_em(symbol=ticker_with_prefix)),
    ]:
        try:
            data = func()
            if data is not None and not data.empty:
                row = data.iloc[0]
                financial_data[label] = {str(k): str(v) for k, v in row.items()}
                report_date = row.get("REPORT_DATE", row.index[0] if hasattr(row.index, '__getitem__') else "N/A")
                p(f"  {label} 报告期：{report_date}")
            else:
                p(f"  {label}: 返回空数据")
        except Exception as e:
            p(f"  {label}获取失败（容错）: {str(e)[:60]}")
    raw_data["financial"] = financial_data

    # ── 5. 主力资金流向（容错：push2 可能被封） ──────────────
    p("\n[5/8] 获取主力资金流向（近10日）...")
    fund_flow_records = []
    try:
        ff = ak.stock_individual_fund_flow(stock=ticker, market=market.lower())
        if ff is not None and not ff.empty:
            recent = ff.tail(10)
            cols   = list(recent.columns)
            for _, row in recent.iterrows():
                rec = {str(c): str(row[c]) for c in cols}
                fund_flow_records.append(rec)
                date_col   = cols[0]
                inflow_col = next((c for c in cols if "净流入" in c and "净额" in c), cols[1] if len(cols) > 1 else None)
                ratio_col  = next((c for c in cols if "净占比" in c), None)
                p(f"  {row[date_col]}: 主力净流入 {row[inflow_col] if inflow_col else 'N/A'} 元  "
                  f"净占比 {row[ratio_col] if ratio_col else 'N/A'}%")
        else:
            p("  资金流向为空（接口可能受限，容错跳过）")
    except Exception as e:
        p(f"  资金流向获取失败（容错跳过）: {str(e)[:60]}")
    raw_data["fund_flow"] = fund_flow_records

    # ── 6. 新闻 ──────────────────────────────────────────────
    p("\n[6/8] 获取最新新闻（前15条）...")
    news_list = []
    try:
        news = ak.stock_news_em(symbol=ticker)
        if news is not None and not news.empty:
            for _, row in news.head(15).iterrows():
                cols_n     = list(row.index)
                title_col  = next((c for c in cols_n if "标题" in c), cols_n[1] if len(cols_n) > 1 else None)
                time_col   = next((c for c in cols_n if "时间" in c or "日期" in c), cols_n[0])
                src_col    = next((c for c in cols_n if "来源" in c or "source" in c.lower()), None)
                rec = {
                    "时间": str(row[time_col]),
                    "标题": str(row[title_col]) if title_col else "",
                    "来源": str(row[src_col])   if src_col   else "",
                }
                news_list.append(rec)
                p(f"  [{rec['时间']}] {rec['标题'][:60]}")
        else:
            p("  东方财富新闻为空，尝试同花顺接口...")
            try:
                news2 = ak.stock_news_ths(code=ticker)
                if news2 is not None and not news2.empty:
                    for _, row in news2.head(15).iterrows():
                        rec = {str(c): str(row[c]) for c in row.index}
                        news_list.append(rec)
            except Exception as e2:
                p(f"  同花顺新闻也失败: {e2}")
    except Exception as e:
        p(f"  新闻获取失败: {e}")
    raw_data["news"] = news_list

    # ── 7. 机构研报评级 ──────────────────────────────────────
    p("\n[7/8] 获取机构研报评级...")
    analyst_ratings = []
    try:
        rating = ak.stock_research_report_em(symbol=ticker)
        if rating is not None and not rating.empty:
            for _, row in rating.head(8).iterrows():
                rec = {str(c): str(row[c]) for c in row.index}
                analyst_ratings.append(rec)
                date_c   = next((c for c in rec if "日期" in c), list(rec.keys())[0])
                inst_c   = next((c for c in rec if "机构" in c), "")
                rating_c = next((c for c in rec if "评级" in c), "")
                target_c = next((c for c in rec if "目标" in c), "")
                p(f"  {rec.get(date_c,'')} | {rec.get(inst_c,'')} | {rec.get(rating_c,'')} | 目标:{rec.get(target_c,'N/A')}")
        else:
            p("  机构研报暂无数据")
    except Exception as e:
        p(f"  机构评级获取失败: {e}")
    raw_data["analyst_ratings"] = analyst_ratings

    # 保存原始数据
    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, ensure_ascii=False, indent=2, default=str)
    p(f"\n  [原始数据已保存: {data_file}]")

    # ── 8. DeepSeek 多智能体分析 ────────────────────────────
    p("\n[8/8] 启动 DeepSeek 多智能体分析...")

    data_ctx = f"""
股票：{ticker_display}
分析日期：{analysis_date}

=== 基本信息 ===
{json.dumps(raw_data.get('info', {}), ensure_ascii=False, indent=2)}

=== 技术指标 ===
{json.dumps(tech_summary, ensure_ascii=False, indent=2)}

=== 近10个交易日行情 ===
{df.tail(10).to_string() if price_data_ok else '暂无数据'}

=== 财务数据 ===
{json.dumps(financial_data, ensure_ascii=False, indent=2, default=str)}

=== 主力资金流向（近10日）===
{json.dumps(fund_flow_records, ensure_ascii=False, indent=2)}

=== 最新新闻 ===
{json.dumps(news_list, ensure_ascii=False, indent=2)}

=== 机构研报评级 ===
{json.dumps(analyst_ratings, ensure_ascii=False, indent=2)}
"""

    def call_chat(system_prompt, user_content, max_tokens=1200, model="deepseek-chat"):
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_content},
            ],
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content

    p("  [分析师-1] 基本面分析...")
    fundamental_report = call_chat(SYS_FUNDAMENTAL, f"请分析{ticker_display}：\n{data_ctx}")
    p("  [基本面完成]")

    p("  [分析师-2] 技术面分析...")
    technical_report = call_chat(SYS_TECHNICAL, f"请分析{ticker_display}：\n{data_ctx}")
    p("  [技术面完成]")

    p("  [分析师-3] 情绪新闻分析...")
    sentiment_report = call_chat(SYS_SENTIMENT, f"请分析{ticker_display}：\n{data_ctx}")
    p("  [情绪分析完成]")

    p("  [决策引擎] deepseek-reasoner 综合推理...")
    rsi_str  = f"{tech_summary['rsi14']:.1f}"    if isinstance(tech_summary.get('rsi14'),      float) else "N/A"
    macd_str = f"{tech_summary['macd']:.4f}"      if isinstance(tech_summary.get('macd'),       float) else "N/A"
    ret5_str = f"{tech_summary['ret_5d_pct']:.2f}%" if isinstance(tech_summary.get('ret_5d_pct'), float) else "N/A"

    combined = f"""
=== 基本面分析 ===
{fundamental_report}

=== 技术面分析 ===
{technical_report}

=== 情绪/新闻分析 ===
{sentiment_report}

=== 核心数据快照 ===
股票：{ticker_display}  日期：{analysis_date}
收盘价：{tech_summary.get('latest_close','N/A')} 元  RSI(14)：{rsi_str}  MACD柱：{macd_str}  近5日：{ret5_str}
"""
    final_decision = call_chat(
        SYS_DECISION,
        f"综合分析{ticker_display}，给出最终投资决策：\n{combined}",
        max_tokens=2000,
        model="deepseek-reasoner",
    )
    p("  [决策完成]")

    # ── 生成 Markdown 报告 ────────────────────────────────────
    def fmt(v, spec=""):
        try:
            return format(float(v), spec) if v not in (None, "N/A", "") else "N/A"
        except Exception:
            return str(v) if v not in (None, "") else "N/A"

    close_price = fmt(tech_summary.get('latest_close'), ".2f")
    ma5_v       = fmt(tech_summary.get('ma5'),   ".2f")
    ma20_v      = fmt(tech_summary.get('ma20'),  ".2f")
    ma60_v      = fmt(tech_summary.get('ma60'),  ".2f")
    bb_lower_v  = fmt(tech_summary.get('bb_lower'), ".2f")
    bb_upper_v  = fmt(tech_summary.get('bb_upper'), ".2f")
    bb_mid_v2   = fmt(tech_summary.get('bb_mid'),   ".2f")
    vol_ratio_v = fmt(tech_summary.get('vol_ratio'), ".2f")
    change_v    = fmt(tech_summary.get('latest_change_pct'), ".2f")

    company_name = raw_data["info"].get("股票简称", ticker_display)

    report_md = f"""# {ticker_display}（{company_name}）投资分析报告

**分析日期**：{analysis_date}
**数据来源**：akshare（东方财富数据）
**分析引擎**：DeepSeek Chat（基本面/技术面/情绪面）+ DeepSeek Reasoner（综合决策）

---

## 关键数据快照

| 指标 | 数值 |
|---|---|
| 最新收盘价 | **{close_price} 元** |
| 当日涨跌幅 | {change_v}% |
| 近5日涨跌幅 | {ret5_str} |
| MA5 / MA20 / MA60 | {ma5_v} / {ma20_v} / {ma60_v} |
| RSI(14) | {rsi_str} |
| MACD柱 | {macd_str} |
| 布林带区间 | [{bb_lower_v} ~ {bb_upper_v}] 中轨 {bb_mid_v2} |
| 量比(5/20日) | {vol_ratio_v} |

---

## 基本面分析

{fundamental_report}

---

## 技术面分析

{technical_report}

---

## 情绪与新闻分析

{sentiment_report}

---

## 最终投资决策

{final_decision}

---

> ⚠️ **免责声明**：本报告由 AI 系统基于公开数据生成，仅供研究参考，不构成投资建议。
> 投资有风险，入市须谨慎，请结合自身风险承受能力和实际情况做出独立判断。
"""

    with open(result_file, "w", encoding="utf-8") as f:
        f.write(report_md)

    p(f"\n  ✓ 报告已保存：{result_file}")
    return {"ticker": ticker_display, "report_file": result_file, "status": "success"}


# ──────────────────────────────────────────────────────────────
# 主入口：批量分析 / 单股 CLI 模式
# 用法：
#   批量模式：python analyze_stock.py
#   单股模式：python analyze_stock.py <ticker> <sh|sz> [YYYY-MM-DD]
#   示例：    python analyze_stock.py 301629 sz 2026-07-05
# ──────────────────────────────────────────────────────────────
def main():
    # ── CLI 参数解析：argv[1]=ticker  argv[2]=sh/sz  argv[3]=日期(可选)
    if len(sys.argv) >= 3:
        cli_ticker = sys.argv[1].strip()
        cli_market = sys.argv[2].strip().lower()
        if cli_market not in ("sh", "sz"):
            print(f"错误：market 必须是 sh 或 sz，当前为 '{cli_market}'", flush=True)
            sys.exit(1)
        cli_date = sys.argv[3].strip() if len(sys.argv) >= 4 else datetime.date.today().strftime("%Y-%m-%d")
        stock_list    = [(cli_ticker, cli_market)]
        analysis_date = cli_date
    else:
        stock_list    = STOCK_LIST
        analysis_date = ANALYSIS_DATE

    date_tag = analysis_date.replace("-", "")

    p("\n" + "★" * 64)
    p(f"  TradingAgents A股批量分析引擎")
    p(f"  分析日期：{analysis_date}")
    p(f"  待分析股票：{len(stock_list)} 只")
    p(f"  输出根目录：{REPORTS_BASE}")
    p("★" * 64)

    results = []
    for i, (ticker, market) in enumerate(stock_list, 1):
        p(f"\n\n{'▶' * 3}  [{i}/{len(stock_list)}] 开始处理 {ticker}.{'SH' if market.lower()=='sh' else 'SZ'}")
        try:
            res = analyze_one(ticker, market, analysis_date)
            results.append(res)
        except Exception as e:
            p(f"  ✗ 分析失败: {e}")
            results.append({"ticker": f"{ticker}.{'SH' if market.lower()=='sh' else 'SZ'}",
                            "report_file": "", "status": f"failed: {e}"})

    # ── 汇总报告 ─────────────────────────────────────────────
    summary_file = os.path.join(REPORTS_BASE, f"batch_summary_{date_tag}.md")
    lines = [
        f"# A股批量分析汇总报告",
        f"",
        f"**分析日期**：{ANALYSIS_DATE}",
        f"**生成时间**：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**分析股票数**：{len(results)}",
        f"",
        f"---",
        f"",
        f"## 分析结果一览",
        f"",
        f"| 股票 | 状态 | 报告文件 |",
        f"|---|---|---|",
    ]
    for r in results:
        status_mark = "✓" if r["status"] == "success" else "✗"
        report_name = os.path.basename(r["report_file"]) if r["report_file"] else "—"
        lines.append(f"| {r['ticker']} | {status_mark} {r['status']} | {report_name} |")

    lines += [
        f"",
        f"---",
        f"",
        f"> ⚠️ 本报告由 AI 系统基于公开数据生成，仅供研究参考，不构成投资建议。",
    ]

    with open(summary_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    p("\n\n" + "=" * 64)
    p("  批量分析完成！")
    p(f"  汇总报告：{summary_file}")
    p("=" * 64)
    for r in results:
        mark = "✓" if r["status"] == "success" else "✗"
        p(f"  {mark} {r['ticker']:15s}  {r.get('report_file', r['status'])}")
    p("=" * 64)


if __name__ == "__main__":
    main()
