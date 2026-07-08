# -*- coding: utf-8 -*-
"""对国金证券 QMT（迅投 xtquant）交易接口的薄封装。

只有本模块在函数内部导入 xtquant —— report_parser / position_sizer 的单元测试
因此不需要安装 xtquant 或运行 QMT 客户端即可跑通。
"""
import logging
import sys
import time

from qmt_trading.position_sizer import PositionInfo

logger = logging.getLogger("qmt_trading")

_QUOTE_WARMUP_SECONDS = 1.0

_OPEN_ORDER_STATUS_NAMES = (
    "ORDER_UNREPORTED",
    "ORDER_WAIT_REPORTING",
    "ORDER_REPORTED",
    "ORDER_PART_SUCC",
)


def _ensure_xtquant_importable(site_packages_path: str):
    try:
        import xtquant  # noqa: F401
    except ImportError:
        if site_packages_path not in sys.path:
            sys.path.append(site_packages_path)
        try:
            import xtquant  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                f"无法导入 xtquant，请确认 QMT 客户端已安装且路径正确："
                f"{site_packages_path}"
            ) from e


class _LoggingCallback:
    """xtquant 回调：把关键事件打到日志，方便下单后核对成交情况。"""

    def on_connected(self):
        logger.info("[QMT] 已连接")

    def on_disconnected(self):
        logger.warning("[QMT] 连接已断开")

    def on_stock_order(self, order):
        logger.info(
            "[QMT][委托] %s %s 状态=%s 委托量=%s 已成交=%s",
            order.stock_code, order.order_id, order.order_status,
            order.order_volume, order.traded_volume,
        )

    def on_stock_trade(self, trade):
        logger.info(
            "[QMT][成交] %s 成交价=%s 成交量=%s",
            trade.stock_code, trade.traded_price, trade.traded_volume,
        )

    def on_order_error(self, order_error):
        logger.error("[QMT][委托失败] %s", getattr(order_error, "error_msg", order_error))

    def on_cancel_error(self, cancel_error):
        logger.error("[QMT][撤单失败] %s", getattr(cancel_error, "error_msg", cancel_error))


class QmtGateway:
    def __init__(self, userdata_path: str, account_id: str, account_type: str = "STOCK"):
        self.userdata_path = userdata_path
        self.account_id = account_id
        self.account_type = account_type
        self._trader = None
        self._account = None

    def connect(self, site_packages_path: str, timeout: float = 10.0):
        _ensure_xtquant_importable(site_packages_path)
        from xtquant import xttrader, xttype

        session_id = int(time.time())
        self._trader = xttrader.XtQuantTrader(self.userdata_path, session_id, _LoggingCallback())
        self._trader.start()
        result = self._trader.connect()
        if result != 0:
            raise RuntimeError(
                f"连接 QMT 客户端失败（返回码 {result}）。请确认已启动国金证券QMT交易端，"
                f"并已登录账号 {self.account_id}，userdata 路径 {self.userdata_path} 是否匹配该客户端实例。"
            )
        self._account = xttype.StockAccount(self.account_id, self.account_type)
        sub_result = self._trader.subscribe(self._account)
        if sub_result != 0:
            raise RuntimeError(f"订阅账号 {self.account_id} 失败（返回码 {sub_result}），请确认账号已在客户端登录")
        logger.info("[QMT] 已连接并订阅账号 %s", self.account_id)

    def disconnect(self):
        if self._trader is not None:
            self._trader.stop()

    def get_asset(self):
        asset = self._trader.query_stock_asset(self._account)
        if asset is None:
            raise RuntimeError("查询账户资产失败，返回为空")
        return {
            "cash": asset.cash,
            "frozen_cash": asset.frozen_cash,
            "market_value": asset.market_value,
            "total_asset": asset.total_asset,
        }

    def get_positions(self) -> dict:
        positions = self._trader.query_stock_positions(self._account) or []
        result = {}
        for p in positions:
            result[p.stock_code] = PositionInfo(
                volume=p.volume,
                can_use_volume=p.can_use_volume,
                market_value=p.market_value,
            )
        return result

    def get_latest_price(self, tickers: list) -> dict:
        from xtquant import xtdata

        # get_full_tick() 在本地行情缓存尚未预热时可能只返回上一交易日收盘快照；
        # 先订阅一次分笔行情、短暂等待缓存刷新，避免拿到滞后价格。
        for ticker in tickers:
            xtdata.subscribe_quote(ticker, period="tick")
        time.sleep(_QUOTE_WARMUP_SECONDS)

        ticks = xtdata.get_full_tick(tickers)
        prices = {}
        for ticker in tickers:
            tick = ticks.get(ticker)
            if tick and tick.get("lastPrice"):
                prices[ticker] = float(tick["lastPrice"])
        return prices

    def place_order(self, ticker: str, side: str, shares: int, limit_price: float) -> int:
        from xtquant import xtconstant

        order_type = xtconstant.STOCK_BUY if side == "BUY" else xtconstant.STOCK_SELL
        order_id = self._trader.order_stock(
            self._account,
            ticker,
            order_type,
            shares,
            xtconstant.FIX_PRICE,
            limit_price,
            strategy_name="analyze_stock_auto",
            order_remark="qmt_trading auto execute",
        )
        if order_id < 0:
            raise RuntimeError(f"下单失败：{ticker} {side} {shares}股 @ {limit_price}")
        return order_id

    def query_orders(self):
        return self._trader.query_stock_orders(self._account) or []

    def query_trades(self):
        return self._trader.query_stock_trades(self._account) or []

    def cancel_open_orders(self) -> list:
        """撤销所有未完全成交（未报/待报/已报/部成）的当日委托，返回 (代码, order_id, 撤单返回码) 列表。"""
        from xtquant import xtconstant

        open_statuses = {getattr(xtconstant, name) for name in _OPEN_ORDER_STATUS_NAMES}
        results = []
        for order in self.query_orders():
            if order.order_status in open_statuses:
                ret = self._trader.cancel_order_stock(self._account, order.order_id)
                results.append((order.stock_code, order.order_id, ret))
        return results
