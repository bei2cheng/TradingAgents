# 分析报告 → QMT 自动交易 使用说明

整个流程分两步：

1. **`reports/analyze_stock.py`** —— 对 `STOCK_LIST` 中的股票做分析，为每只股票生成一份带"交易决策"（操作方向/建议仓位等）的 Markdown 报告。
2. **`qmt_trading.run_strategy`** —— 读取这些报告，换算成具体的委托单（股数/限价），通过国金证券 QMT 客户端下单（模拟盘或实盘）。

```
reports/analyze_stock.py  →  reports/{TICKER}.{SH|SZ}_{DATE}/analysis_report_{DATE}.md
                                        │
                                        ▼
                          qmt_trading.run_strategy plan/execute
                                        │
                                        ▼
                          reports/qmt_orders_{DATE}_{mode}.md（预览）
                          reports/qmt_orders_log_{DATE}.jsonl（下单日志）
```

---

## 一、生成分析报告：`reports/analyze_stock.py`

### 依赖
`akshare`、`baostock`、`pandas`、`numpy`、`openai`（走 DeepSeek 兼容接口）。

需要设置环境变量 `DEEPSEEK_API_KEY`（.env 中配置）；代码里有一个内置默认 key 仅作兜底，**生产使用请务必自行在 `.env` 里设置 `DEEPSEEK_API_KEY`，不要依赖内置默认值**。

### 配置股票列表
编辑 [reports/analyze_stock.py](../reports/analyze_stock.py) 顶部的 `STOCK_LIST`（`(代码, sh|sz)` 元组列表）。这个列表同时也是 `qmt_trading` 的交易白名单来源——不在这里的股票不会被自动下单。

### 用法

```bash
# 批量模式：分析 STOCK_LIST 里全部股票，日期默认今天
python reports/analyze_stock.py

# 单股模式：只分析一只股票，日期可选（默认今天）
python reports/analyze_stock.py <代码> <sh|sz> [YYYY-MM-DD]
# 示例
python reports/analyze_stock.py 301629 sz 2026-07-05
```

### 输出
- `reports/{代码}.{SH|SZ}_{YYYYMMDD}/analysis_report_{YYYYMMDD}.md`：单股详细报告，末尾"交易决策"章节包含：
  - `操作方向`：BUY / SELL / HOLD
  - `建议仓位`：重仓 / 中仓 / 轻仓 / 空仓
  - 建议操作价区、止损位、6个月目标价（仅供人工参考，`qmt_trading` 不解析这两项）
- `reports/batch_summary_{YYYYMMDD}.md`：批量分析汇总表（仅批量模式生成）

---

## 二、自动执行交易：`qmt_trading.run_strategy`

### 环境
```bash
conda activate tradingagents
```
> `tradingagents` 环境已固定为 Python 3.11，以匹配国金 QMT 客户端 `xtquant` 的 `xtpythonclient.cp311-win_amd64.pyd` 二进制（更高版本 Python 无对应编译产物，import 会直接失败）。**不要**把这个环境升级回 3.12/3.13。

运行前必须：
1. 启动对应的 QMT 客户端（模拟盘 / 实盘是两个独立安装目录、两套账号）并登录，确保生成了 `userdata_mini` 目录（可用 `tasklist | findstr XtMiniQmt` 确认后台的 `XtMiniQmt.exe` 已启动）。
2. 在 `.env` 中配置好下面这些变量（完整列表见 [.env.example](../.env.example)）：

| 变量 | 说明 |
|---|---|
| `QMT_SITE_PACKAGES_PATH` | QMT 客户端里 `xtquant` 所在的 `site-packages` 目录 |
| `QMT_SIM_USERDATA_PATH` / `QMT_LIVE_USERDATA_PATH` | 模拟盘 / 实盘各自客户端实例的 `userdata_mini` 目录 |
| `QMT_SIM_ACCOUNT_ID` / `QMT_LIVE_ACCOUNT_ID` | 模拟盘 / 实盘资金账号（必填，未配置会直接报错拒绝运行） |
| `QMT_WEIGHT_HEAVY/MEDIUM/LIGHT/EMPTY` | 重仓/中仓/轻仓/空仓 → 目标仓位占总资产比例（默认 35%/25%/15%/0%） |
| `QMT_MAX_SINGLE_STOCK_PCT` / `QMT_MAX_TOTAL_POSITION_PCT` | 单股 / 总仓位上限（默认 20% / 80%） |
| `QMT_LOT_SIZE` / `QMT_SLIPPAGE_PCT` / `QMT_MIN_ORDER_NOTIONAL` | 每手股数、限价滑点、最小下单金额 |

### 命令

```bash
# 1. 只读查询：验证连接，打印资产/持仓/当日委托
python -m qmt_trading.run_strategy status --mode sim

# 2. 生成委托预览（不下单），会解析最新分析报告并保存预览到
#    reports/qmt_orders_{日期}_{mode}.md
python -m qmt_trading.run_strategy plan --mode sim [--date YYYYMMDD]

# 3. 真正下单：在 plan 基础上调用 QMT 下单接口
python -m qmt_trading.run_strategy execute --mode sim [--date YYYYMMDD] [--yes]
```

`--mode` 支持 `sim`（模拟盘）/ `live`（实盘）。

### `execute` 的安全限制
- 只交易 `STOCK_LIST` 白名单内的股票。
- 只在 A 股交易时间下单（09:30-11:30 / 13:00-15:00，工作日），`sim` 模式可加 `--force-outside-hours` 跳过（仅用于联调）。
- 下单前会打印委托计划，需要手动输入确认（`sim` 输入 `yes`，`live` 输入 `CONFIRM`），或用 `--yes` 跳过确认。
- `live` 模式额外要求显式传入 `--i-understand-real-money`，否则直接拒绝执行。
- 每笔下单结果（成功/失败、委托号）追加写入 `reports/qmt_orders_log_{日期}.jsonl`。

### 仓位计算逻辑（`plan`/`execute` 共用）
1. 只处理白名单内、有可解析 `操作方向`+`建议仓位` 的股票，`HOLD` 或解析失败的一律跳过。
2. 单股目标仓位先按 `QMT_MAX_SINGLE_STOCK_PCT` 封顶。
3. 所有 BUY 方向目标仓位求和，若超过 `QMT_MAX_TOTAL_POSITION_PCT`，按比例整体缩放。
4. 按「目标市值 − 当前持仓市值」算出买卖差额，换算成股数（按 `QMT_LOT_SIZE` 取整，买入受可用现金约束，卖出受可用持仓约束）；`SELL`+空仓 视为清仓信号，直接卖出全部可用持仓（不做百手取整）。
5. 低于 `QMT_MIN_ORDER_NOTIONAL` 的委托单跳过。
6. 限价 = 最新价 ×(1 ± `QMT_SLIPPAGE_PCT`)（买入加价、卖出减价）。

### 常见问题
- `ImportError: cannot import name 'xtpythonclient' from 'xtquant'`：Python 版本与 `xtquant` 的编译产物不匹配，确认当前环境是 Python 3.11（见上文环境说明）。
- `连接 QMT 客户端失败（返回码 -1）`：对应 `--mode` 的 QMT 客户端没有启动/没有登录，或 `userdata_mini` 路径没有指向正确的客户端实例；用 `tasklist | findstr XtMiniQmt` 确认后台服务是否已启动。
- 未配置 `QMT_SIM_ACCOUNT_ID` / `QMT_LIVE_ACCOUNT_ID`：会在启动时直接抛出 `RuntimeError`，按提示在 `.env` 里补上对应账号。

---

## 三、单元测试（不需要 QMT 客户端/xtquant）

```bash
pytest tests/test_qmt_report_parser.py tests/test_qmt_position_sizer.py -v
```

覆盖报告解析（方向/仓位档位提取）和仓位计算（封顶、总仓位缩放、清仓、白名单过滤等纯逻辑），无需安装 xtquant 或启动 QMT 客户端即可运行。
