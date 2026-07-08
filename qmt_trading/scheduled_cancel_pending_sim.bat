@echo off
cd /d E:\github\TradingAgents
set PYTHONUTF8=1
"C:\Users\fengzm\anaconda3\envs\tradingagents\python.exe" -m qmt_trading.run_strategy cancel-pending --mode sim >> reports\qmt_scheduled_run.log 2>&1
