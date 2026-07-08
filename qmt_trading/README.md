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

# 4. 撤销所有未完全成交的当日委托（未报/待报/已报/部成），建议收盘前执行，避免资金一直被冻结
python -m qmt_trading.run_strategy cancel-pending --mode sim
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
- 委托一直显示"已报"、成交量为 0：`status`/`cancel-pending` 打印的委托状态是 xtquant 原始状态码（`50`=已报未成，`55`=部成，`56`=已成，`54`=已撤，`57`=废单）。全天没有成交常见原因：①模拟盘的撮合机制通常只在下单那一刻按当时快照做一次性判断能否立即成交，不会像真实交易所那样持续追踪后续行情去撮合挂单；②`plan`/`execute` 取的最新价依赖本地行情缓存，若缓存尚未预热可能拿到上一交易日收盘价（`get_latest_price` 已在下单前加了 `subscribe_quote` + 短暂等待来缓解这个问题，但极端情况下仍可能取到偏旧的价格）。未成交的委托不会自动撤销、资金会一直被冻结，建议收盘前用 `cancel-pending` 手动清理（也可以为它单独建一个收盘前的计划任务）。

---

## 三、Windows 计划任务自动化（每个工作日免手动运行）

适用场景：早上出门前在家里这台电脑上启动并登录好 QMT 模拟盘客户端，之后不用再手动敲命令，Windows 会自动在交易时段内跑 `execute` 下单、收盘前跑 `cancel-pending` 清理未成交单。

### 已创建的两个计划任务

| 任务名 | 时间（工作日） | 执行脚本 | 作用 |
|---|---|---|---|
| `QMT_AutoTrade_Sim` | 09:31 | [qmt_trading/scheduled_run_sim.bat](scheduled_run_sim.bat) | `execute --mode sim --yes` 自动下单 |
| `QMT_AutoTrade_Sim_CancelPending` | 14:57 | [qmt_trading/scheduled_cancel_pending_sim.bat](scheduled_cancel_pending_sim.bat) | `cancel-pending --mode sim` 撤销当天未成交委托，释放冻结资金 |

两个 `.bat` 都是先 `cd /d` 到仓库目录，再用 `tradingagents` 环境的 `python.exe`（`C:\Users\fengzm\anaconda3\envs\tradingagents\python.exe`，不依赖 `conda activate`）跑对应命令，输出统一追加到 `reports\qmt_scheduled_run.log`。

**前提**：计划任务只负责调用 `run_strategy`，不会帮你打开/登录 QMT 客户端——09:31 之前必须已手动启动并登录国金 QMT 模拟盘客户端，否则 `execute` 会因连不上客户端而失败（失败信息记在日志里，不会主动提醒）。

**注意**：`execute` 用了 `--yes`，跳过了手动输入 `yes` 确认这一步安全检查，是无人值守自动化的必要代价（目前仅用于 sim 模拟盘，不涉及真实资金）。

### 常用管理命令

在 git-bash 里执行 `schtasks` 时，单斜杠参数（如 `/tn`）会被 MSYS 误当成文件路径转换，需要加 `MSYS_NO_PATHCONV=1` 前缀：

```bash
# 查看任务详情
MSYS_NO_PATHCONV=1 schtasks /query /tn "QMT_AutoTrade_Sim" /v /fo LIST
MSYS_NO_PATHCONV=1 schtasks /query /tn "QMT_AutoTrade_Sim_CancelPending" /v /fo LIST

# 临时禁用（不删除，比如当天不想自动交易）
MSYS_NO_PATHCONV=1 schtasks /change /tn "QMT_AutoTrade_Sim" /disable
MSYS_NO_PATHCONV=1 schtasks /change /tn "QMT_AutoTrade_Sim_CancelPending" /disable

# 重新启用
MSYS_NO_PATHCONV=1 schtasks /change /tn "QMT_AutoTrade_Sim" /enable

# 彻底删除
MSYS_NO_PATHCONV=1 schtasks /delete /tn "QMT_AutoTrade_Sim" /f
MSYS_NO_PATHCONV=1 schtasks /delete /tn "QMT_AutoTrade_Sim_CancelPending" /f
```

也可以直接打开 Windows「任务计划程序」图形界面，在根目录下找到这两个任务手动调整触发时间或禁用。

---

## 四、单元测试（不需要 QMT 客户端/xtquant）

```bash
pytest tests/test_qmt_report_parser.py tests/test_qmt_position_sizer.py -v
```

覆盖报告解析（方向/仓位档位提取）和仓位计算（封顶、总仓位缩放、清仓、白名单过滤等纯逻辑），无需安装 xtquant 或启动 QMT 客户端即可运行。
