# -*- coding: utf-8 -*-
"""QMT（国金证券迅投极简交易端）自动交易执行模块。

将 reports/analyze_stock.py 生成的分析报告转化为 QMT 委托单并下单，
支持模拟盘 / 实盘两套账号，提供只读预览（plan）与真实下单（execute）两种模式。
"""
