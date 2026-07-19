# 策略文字转代码 + A股回测 + 评级 + 国金证券实盘/模拟盘 使用说明

`quant_strategy` 把"文字描述策略"到"实盘下单"整条链路串起来：

```
文字描述 --define--> 策略JSON(DSL/code)  --backtest--> 回测报告(Markdown+指标+权益曲线)
                            │
                            ├--rate----> 某股票在某日期的 BUY/SELL/HOLD 评级（可解释）
                            │
                            └--trade---> 适配成 qmt_trading.TradeDecision
                                              │
                                              ▼
                                  qmt_trading 既有的仓位计算 + QMT 下单链路（模拟盘/实盘）
```

评级和回测复用同一套信号引擎（`strategy/engine.py::generate_signals`），保证评级结论与回测逻辑 100% 一致、可复现。实盘/模拟盘对接不重复造轮子——直接复用 [qmt_trading](../qmt_trading/README.md) 已有的仓位计算与 QMT 下单代码。

---

## 一、策略文字 → 可执行策略：`define`

```bash
python -m quant_strategy.cli define --text "MA5上穿MA20买入，MA5下穿MA20卖出" --name ma_cross
```

处理逻辑（DSL 优先，codegen 兜底）：
1. 先调用 LLM（默认 DeepSeek，需要 `.env` 里配置 `DEEPSEEK_API_KEY`）把文字描述映射成一组预定义的技术指标规则（DSL：`strategy/schema.py` 里的 `IndicatorRef`/`Condition`/`Rule`），支持 MA/EMA/MACD/RSI/布林带/量比/N日高低点等指标与 AND/OR/NOT 组合。
2. 如果描述涉及 DSL 无法表达的信息（财报、消息面等非技术指标内容），自动降级为让 LLM 直接生成一段 Python 代码（`generate_signals(df) -> pd.Series`），代码必须先通过 `strategy/validator.py` 的 AST 白名单校验（禁止 import、eval/exec/open、dunder 属性访问等）才会被采纳。
3. 两条路径都失败时抛出 `DslUnsupportedError`，不会生成一个"看似能跑但语义不对"的策略。

生成的策略保存为 `strategies/{name}.json`（已加入 `.gitignore`，属于本地产物）。

---

## 二、回测：`backtest`

```bash
python -m quant_strategy.cli backtest \
  --strategy ma_cross \
  --codes 600519.SH,000001.SZ \
  --start 2024-01-01 --end 2026-07-01
```

回测引擎（`backtest/engine.py`）是自建的轻量事件驱动引擎，专门模拟A股规则：
- **T+1**：当日买入的份额，下一交易日才计入可卖出（`backtest/portfolio.py::Position.sellable`）
- **100股整手**：买入/卖出股数按 `QS_LOT_SIZE`（默认100）向下取整
- **涨跌停不可成交**：当日收盘价相对前收盘涨跌幅达到 `QS_PRICE_LIMIT_PCT`（默认±10%）时，当天跳过该笔买入/卖出
- 固定滑点（`QS_SLIPPAGE_PCT`）+ 佣金（`QS_COMMISSION_RATE`，有最低佣金 `QS_MIN_COMMISSION`）+ 印花税（`QS_STAMP_TAX_RATE`，仅卖出）

行情数据来自 `data/market_data.py`（baostock 日线前复权，与 `reports/analyze_stock.py` 同一数据源），本地缓存在 `quant_strategy/data_cache/`（已 gitignore）。

输出的 Markdown 报告（默认落在 `strategies/reports/`）包含：
- 参数摘要（股票池/区间/初始资金）
- 指标汇总：总收益率、年化收益率、最大回撤、夏普比率、卡玛比率、胜率、盈亏比、相对沪深300（`QS_BENCHMARK_CODE`）的超额收益
- 权益曲线（装了 `matplotlib` 则输出 PNG，否则退化为文本 ASCII 曲线）
- 逐笔交易明细

---

## 三、某股票在某日期的评级：`rate`

```bash
python -m quant_strategy.cli rate --strategy ma_cross --code 600519.SH --date 2026-07-18
```

评级结论**纯来自量化策略信号**，不叠加任何 LLM 定性判断——本质上是"只跑到目标日期这一天"的回测（`rating/rater.py`），所以同一个策略对同一天给出的评级，与把该日期包含在回测区间内跑出来的信号一定一致。DSL 模式下还会输出具体触发的买入/卖出条件（可解释性），例如 `ma_window5 cross_above ma_window20`。

---

## 四、对接国金证券 QMT：`trade`

```bash
# 生成委托预览，不下单
python -m quant_strategy.cli trade plan \
  --strategy ma_cross --codes 600519.SH,000001.SZ \
  --date 2026-07-18 --mode sim

# 生成委托并真实下单（sim=模拟盘 / live=实盘）
python -m quant_strategy.cli trade execute \
  --strategy ma_cross --codes 600519.SH,000001.SZ \
  --date 2026-07-18 --mode sim
```

内部流程（`live/bridge.py`）：对每只股票跑 `rate()` 得到 BUY/SELL/HOLD，再适配成 `qmt_trading.report_parser.TradeDecision`（BUY→仓位档位 `--buy-label` 指定，默认"中仓"；SELL→"空仓"即全部清仓；HOLD 不产生委托），然后**直接复用** `qmt_trading.position_sizer.build_order_plans`（单股/总仓位封顶、白名单过滤、百手取整）和 `qmt_trading.qmt_gateway.QmtGateway`（连接QMT、查资产/持仓/行情、下单）——不重新实现任何下单或风控逻辑。

运行前的环境要求与安全限制，与 [qmt_trading/README.md](../qmt_trading/README.md) 完全一致：
- 需要先启动并登录对应的国金证券 QMT 客户端（模拟盘/实盘），`.env` 里配置好 `QMT_*` 系列变量（账号、仓位档位权重、单股/总仓位上限等）
- `conda activate tradingagents`（固定 Python 3.11，匹配 `xtquant` 的编译产物）
- `trade execute` 只在A股交易时间下单，`live` 模式必须显式传 `--i-understand-real-money`，下单前需要交互确认（或 `--yes` 跳过）

---

## 五、单元测试（不需要网络/xtquant）

```bash
pytest tests/test_quant_strategy_*.py -v
```

覆盖 DSL 序列化、指标计算、AST 安全校验、LLM 文本转策略（mock LLM 返回）、回测引擎（T+1/整手/涨跌停/盈亏计算）、指标计算、评级与回测信号一致性、以及适配 `qmt_trading.TradeDecision` 的转换逻辑，均使用合成数据/mock，不依赖 baostock 网络请求或 xtquant。

---

## 目录结构

```
quant_strategy/
  config.py              # A股规则常量、回测默认参数、LLM配置（均可用 .env 覆盖，见下）
  strategy/
    schema.py            # DSL数据模型：IndicatorRef/Condition/Rule/StrategySpec
    indicators.py         # MA/EMA/MACD/RSI/布林带/量比/N日高低点
    compiler.py           # 文本 -> DSL/codegen（调用LLM）
    validator.py          # codegen代码的AST白名单安全校验
    codegen.py            # 校验通过的codegen代码在受限命名空间执行
    engine.py             # 统一信号引擎：generate_signals(spec, df)
  data/market_data.py     # baostock日线行情获取+本地缓存
  backtest/
    portfolio.py          # 持仓/现金/权益曲线（T+1、成本核算）
    engine.py             # 事件驱动回测循环
    metrics.py            # 总收益/年化/回撤/夏普/卡玛/胜率/盈亏比/超额收益
    report.py             # Markdown回测报告生成
  rating/rater.py          # 单日截面评级（复用回测同一信号引擎）
  live/bridge.py           # 适配成 qmt_trading.TradeDecision，对接既有下单链路
  cli.py                   # define / backtest / rate / trade 统一入口
  strategies/              # 生成的策略JSON + 回测报告（已gitignore）
  data_cache/              # baostock行情缓存（已gitignore）
```

## 常用环境变量（`.env`，均有默认值，非必填）

| 变量 | 说明 | 默认值 |
|---|---|---|
| `QS_LOT_SIZE` | 每手股数 | 100 |
| `QS_PRICE_LIMIT_PCT` / `QS_ST_PRICE_LIMIT_PCT` | 普通股/ST股涨跌停幅度 | 0.10 / 0.05 |
| `QS_BACKTEST_INITIAL_CASH` | 回测初始资金 | 1,000,000 |
| `QS_COMMISSION_RATE` / `QS_MIN_COMMISSION` | 佣金费率 / 单笔最低佣金 | 0.0003 / 5.0 |
| `QS_STAMP_TAX_RATE` | 印花税（仅卖出） | 0.001 |
| `QS_SLIPPAGE_PCT` | 回测成交滑点 | 0.001 |
| `QS_POSITION_PCT_PER_TRADE` | 单只股票仓位比例，0表示按股票数等权 | 0 |
| `QS_BENCHMARK_CODE` | 计算超额收益的基准指数 | 000300.SH（沪深300） |
| `QS_LLM_BASE_URL` / `QS_LLM_MODEL` | 文本转策略用的LLM接入点 | DeepSeek 兼容接口 |

QMT 相关的 `QMT_*` 变量沿用 [qmt_trading](../qmt_trading/README.md) 的配置，`trade` 子命令内部直接调用 `qmt_trading.config.load_config()`。
