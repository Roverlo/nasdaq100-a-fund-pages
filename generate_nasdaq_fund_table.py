import html
import json
import math
import re
import sys
import argparse
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.error import URLError
from urllib.request import Request, urlopen


DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent
TRACKING_FILENAME = "portfolio_tracking.json"
TRACKING_SCHEMA_VERSION = 1
BEIJING_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")
AUTO_REFRESH_TIMES_BEIJING = ("08:45", "16:45", "23:15")
PERSONAL_TRACKING_FIELDS = ("market_value", "cost_basis", "profit", "return_rate")


def now_beijing() -> datetime:
    return datetime.now(BEIJING_TZ)


FUND_CODES = [
    "019441",
    "040046",
    "000834",
    "539001",
    "018966",
    "016452",
    "270042",
    "019172",
    "019547",
    "019736",
    "019524",
    "018043",
    "016055",
    "016532",
    "015299",
    "161130",
]


FUND_DISPLAY_LABELS = {
    "019441": "万家",
    "040046": "华安",
    "000834": "大成",
    "539001": "建信",
    "018966": "汇添富",
    "016452": "南方",
    "270042": "广发",
    "019172": "摩根",
    "019547": "招商",
    "019736": "宝盈",
    "019524": "华泰柏瑞",
    "018043": "天弘",
    "016055": "博时",
    "016532": "嘉实",
    "015299": "华夏",
    "161130": "易方达",
}


OWNED_CODES = {
    "019172",
    "018966",
    "539001",
    "000834",
    "040046",
    "019441",
    "016452",
    "019547",
}


HOLDING_AMOUNTS = {
    "016452": 250,
    "018966": 100,
    "539001": 100,
    "019441": 50,
    "019172": 20,
    "019547": 20,
    "000834": 10,
    "040046": 10,
}


AUTO_INVESTING_CODES = {
    "019172",
    "040046",
    "019441",
    "016452",
    "270042",
    "019547",
    "019524",
}


NEW_AUTO_INVESTING_CODES = {
}


PAUSED_AUTO_INVESTING_CODES = {
    "018966",
    "539001",
    "000834",
    "019736",
}


AUTO_INVEST_AMOUNTS = {
    "040046": 10,
    "019441": 200,
    "016452": 50,
    "270042": 10,
    "019172": 10,
    "019547": 10,
    "019524": 10,
}


PAUSED_AUTO_INVEST_AMOUNTS = {
    "018966": 100,
    "539001": 100,
    "000834": 10,
    "019736": 10,
}


AUTO_INVEST_FREQUENCY = "日定投"
AUTO_INVEST_NEXT_DEBIT_DATE = "2026-06-22"


AGENCY_LIMIT_LABELS = {
    "021778": "无",
    "021000": "无",
}


DIRECT_LIMIT_ANNOUNCEMENT_KEYWORDS = ("大额申购", "限制申购", "申购金额限制", "业务限制金额", "限制金额", "限购")


SCORING_WEIGHTS = {
    "three_year": 0.35,
    "one_year": 0.20,
    "tracking_error": 0.20,
    "base_fee": 0.15,
    "fund_size": 0.06,
    "buy_rate": 0.02,
    "free_days": 0.02,
}


SCORING_RULES = [
    {
        "key": "three_year",
        "label": "近3年收益",
        "weight": SCORING_WEIGHTS["three_year"],
        "direction": "越高越好",
        "method": "东方财富 SYL_3Y，同池归一化",
        "reason": "核心目标是长期收益优先；机构和指数基金社区通常会先看长期业绩是否稳定跟上标的。",
    },
    {
        "key": "one_year",
        "label": "近1年收益",
        "weight": SCORING_WEIGHTS["one_year"],
        "direction": "越高越好",
        "method": "东方财富 SYL_1N，同池归一化",
        "reason": "保留近端表现，避免只看长期旧数据；权重低于 3 年收益，防止追短期热点。",
    },
    {
        "key": "tracking_error",
        "label": "跟踪误差",
        "weight": SCORING_WEIGHTS["tracking_error"],
        "direction": "越低越好",
        "method": "天天基金特色数据页，反向归一化",
        "reason": "iShares、State Street 和 Bogleheads 都把跟踪质量视为指数基金核心指标；误差越小越稳定。",
    },
    {
        "key": "base_fee",
        "label": "管理+托管",
        "weight": SCORING_WEIGHTS["base_fee"],
        "direction": "越低越好",
        "method": "管理费率 + 托管费率，反向归一化",
        "reason": "Vanguard 等机构长期强调低费率会改善投资者净回报；管理费和托管费是长期持有的持续拖累。",
    },
    {
        "key": "fund_size",
        "label": "基金规模",
        "weight": SCORING_WEIGHTS["fund_size"],
        "direction": "适度越大越好",
        "method": "东方财富 ENDNAV 转亿元，取 log10 后归一化",
        "reason": "规模只作稳定性和流动性辅助项；它不替代收益、跟踪质量和费用。",
    },
    {
        "key": "buy_rate",
        "label": "买入费率",
        "weight": SCORING_WEIGHTS["buy_rate"],
        "direction": "越低越好",
        "method": "申购费率，反向归一化",
        "reason": "一次性交易成本会影响定投入场，但长期影响弱于持续费用和跟踪质量。",
    },
    {
        "key": "free_days",
        "label": "赎回灵活性",
        "weight": SCORING_WEIGHTS["free_days"],
        "direction": "越短越好",
        "method": "达到 0% 赎回费所需天数，反向归一化",
        "reason": "赎回灵活性是辅助条件，不应压过收益、跟踪误差和持续费用。",
    },
]


FALLBACK = {
    "019441": {
        "name": "万家纳斯达克100指数(QDII)A",
        "daily_limit": 10000,
        "direct_limit": 10000,
        "buy_rate": 0.10,
        "management_fee": 0.50,
        "custody_fee": 0.15,
        "sales_fee": 0.00,
        "one_year": 26.48,
        "day_change": -0.95,
        "redemption_rules": [("<7天", 1.50), ("7-30天", 0.10), ("≥30天", 0.00)],
        "free_after_days": 30,
    },
    "019442": {
        "name": "万家纳斯达克100指数(QDII)C",
        "daily_limit": 10000,
        "direct_limit": 10000,
        "buy_rate": 0.00,
        "management_fee": 0.50,
        "custody_fee": 0.15,
        "sales_fee": 0.20,
        "one_year": 26.22,
        "day_change": -0.95,
        "redemption_rules": [("<7天", 1.50), ("≥7天", 0.00)],
        "free_after_days": 7,
    },
    "040046": {
        "name": "华安纳斯达克100ETF联接(QDII)A",
        "daily_limit": 10,
        "direct_limit": 1000,
        "buy_rate": 0.12,
        "management_fee": 0.60,
        "custody_fee": 0.20,
        "sales_fee": 0.00,
        "one_year": 28.54,
        "day_change": -1.02,
        "redemption_rules": [("<7天", 1.50), ("≥7天", 0.00)],
        "free_after_days": 7,
    },
    "014978": {
        "name": "华安纳斯达克100ETF联接(QDII)C",
        "daily_limit": 10,
        "direct_limit": 1000,
        "buy_rate": 0.00,
        "management_fee": 0.60,
        "custody_fee": 0.20,
        "sales_fee": 0.20,
        "one_year": 28.29,
        "day_change": -1.02,
        "redemption_rules": [("<7天", 1.50), ("≥7天", 0.00)],
        "free_after_days": 7,
    },
    "021778": {
        "name": "广发纳指100ETF联接(QDII)人民币F",
        "daily_limit": None,
        "agency_limit_label": "无",
        "direct_limit": 1000,
        "buy_rate": 0.00,
        "management_fee": 0.80,
        "custody_fee": 0.20,
        "sales_fee": 0.18,
        "one_year": 27.65,
        "day_change": -1.00,
        "redemption_rules": [("<7天", 1.50), ("≥7天", 0.00)],
        "free_after_days": 7,
    },
    "021000": {
        "name": "南方纳斯达克100指数发起(QDII)I",
        "daily_limit": None,
        "agency_limit_label": "无",
        "direct_limit": 1000,
        "buy_rate": 0.00,
        "management_fee": 0.50,
        "custody_fee": 0.15,
        "sales_fee": 0.01,
        "one_year": 27.04,
        "day_change": -0.98,
        "redemption_rules": [("<7天", 1.50), ("≥7天", 0.00)],
        "free_after_days": 7,
    },
    "000834": {
        "name": "大成纳斯达克100ETF联接(QDII)A",
        "daily_limit": 10,
        "direct_limit": 100,
        "buy_rate": 0.12,
        "management_fee": 0.80,
        "custody_fee": 0.20,
        "sales_fee": 0.00,
        "one_year": 27.50,
        "day_change": -1.02,
        "redemption_rules": [("<7天", 1.50), ("7-365天", 0.50), ("365-730天", 0.25), ("≥730天", 0.00)],
        "free_after_days": 730,
    },
    "008971": {
        "name": "大成纳斯达克100ETF联接(QDII)C",
        "daily_limit": 10,
        "direct_limit": 100,
        "buy_rate": 0.00,
        "management_fee": 0.80,
        "custody_fee": 0.20,
        "sales_fee": 0.30,
        "one_year": 27.12,
        "day_change": -1.02,
        "redemption_rules": [("<7天", 1.50), ("≥7天", 0.00)],
        "free_after_days": 7,
    },
    "539001": {
        "name": "建信纳斯达克100指数(QDII)A",
        "daily_limit": 100,
        "direct_limit": 100,
        "buy_rate": 0.12,
        "management_fee": 0.80,
        "custody_fee": 0.20,
        "sales_fee": 0.00,
        "one_year": 26.37,
        "day_change": -0.93,
        "redemption_rules": [("<7天", 1.50), ("7-30天", 0.50), ("30-90天", 0.30), ("≥90天", 0.00)],
        "free_after_days": 90,
    },
    "023422": {
        "name": "建信纳斯达克100指数(QDII)D",
        "daily_limit": 100,
        "direct_limit": 100,
        "buy_rate": 0.00,
        "management_fee": 0.80,
        "custody_fee": 0.20,
        "sales_fee": 0.30,
        "one_year": 25.99,
        "day_change": -0.93,
        "redemption_rules": [("<7天", 1.50), ("7-30天", 1.00), ("≥30天", 0.00)],
        "free_after_days": 30,
    },
    "012752": {
        "name": "建信纳斯达克100指数(QDII)C",
        "daily_limit": 100,
        "direct_limit": 100,
        "buy_rate": 0.00,
        "management_fee": 0.80,
        "custody_fee": 0.20,
        "sales_fee": 0.30,
        "one_year": 25.99,
        "day_change": -0.93,
        "redemption_rules": [("<7天", 1.50), ("≥7天", 0.00)],
        "free_after_days": 7,
    },
    "018966": {
        "name": "汇添富纳斯达克100ETF联接(QDII)A",
        "daily_limit": 100,
        "direct_limit": 100,
        "buy_rate": 0.12,
        "management_fee": 0.50,
        "custody_fee": 0.15,
        "sales_fee": 0.00,
        "one_year": 25.65,
        "day_change": -0.96,
        "redemption_rules": [("<7天", 1.50), ("≥7天", 0.00)],
        "free_after_days": 7,
    },
    "021773": {
        "name": "汇添富纳斯达克100ETF联接(QDII)E",
        "daily_limit": 100,
        "direct_limit": 100,
        "buy_rate": 0.00,
        "management_fee": 0.50,
        "custody_fee": 0.15,
        "sales_fee": 0.10,
        "one_year": 25.53,
        "day_change": -0.97,
        "redemption_rules": [("<7天", 1.50), ("≥7天", 0.00)],
        "free_after_days": 7,
    },
    "018967": {
        "name": "汇添富纳斯达克100ETF联接(QDII)C",
        "daily_limit": 100,
        "direct_limit": 100,
        "buy_rate": 0.00,
        "management_fee": 0.50,
        "custody_fee": 0.15,
        "sales_fee": 0.40,
        "one_year": 25.16,
        "day_change": -0.96,
        "redemption_rules": [("<7天", 1.50), ("≥7天", 0.00)],
        "free_after_days": 7,
    },
    "016452": {
        "name": "南方纳斯达克100指数(QDII)A",
        "daily_limit": 50,
        "direct_limit": 50,
        "buy_rate": 0.12,
        "management_fee": 0.50,
        "custody_fee": 0.15,
        "sales_fee": 0.00,
        "one_year": 27.10,
        "day_change": -0.98,
        "redemption_rules": [("<7天", 1.50), ("≥7天", 0.00)],
        "free_after_days": 7,
    },
    "016453": {
        "name": "南方纳斯达克100指数(QDII)C",
        "daily_limit": 50,
        "direct_limit": 50,
        "buy_rate": 0.00,
        "management_fee": 0.50,
        "custody_fee": 0.15,
        "sales_fee": 0.10,
        "one_year": 26.97,
        "day_change": -0.98,
        "redemption_rules": [("<7天", 1.50), ("≥7天", 0.00)],
        "free_after_days": 7,
    },
    "270042": {
        "name": "广发纳斯达克100ETF联接人民币(QDII)A",
        "daily_limit": 10,
        "direct_limit": 10,
        "buy_rate": 0.13,
        "management_fee": 0.80,
        "custody_fee": 0.20,
        "sales_fee": 0.00,
        "one_year": 27.89,
        "day_change": -1.00,
        "redemption_rules": [("<7天", 1.50), ("7-365天", 0.50), ("365-730天", 0.30), ("≥730天", 0.00)],
        "free_after_days": 730,
    },
    "006479": {
        "name": "广发纳斯达克100ETF联接人民币(QDII)C",
        "daily_limit": 10,
        "direct_limit": 10,
        "buy_rate": 0.00,
        "management_fee": 0.80,
        "custody_fee": 0.20,
        "sales_fee": 0.20,
        "one_year": 27.64,
        "day_change": -1.00,
        "redemption_rules": [("<7天", 1.50), ("≥7天", 0.00)],
        "free_after_days": 7,
    },
    "019172": {
        "name": "摩根纳斯达克100指数(QDII)A",
        "daily_limit": 10,
        "direct_limit": 10,
        "buy_rate": 0.12,
        "management_fee": 0.50,
        "custody_fee": 0.10,
        "sales_fee": 0.00,
        "one_year": 27.56,
        "day_change": -0.91,
        "redemption_rules": [("<7天", 1.50), ("≥7天", 0.00)],
        "free_after_days": 7,
    },
    "019173": {
        "name": "摩根纳斯达克100指数(QDII)C",
        "daily_limit": 10,
        "direct_limit": 10,
        "buy_rate": 0.00,
        "management_fee": 0.50,
        "custody_fee": 0.10,
        "sales_fee": 0.30,
        "one_year": 27.20,
        "day_change": -0.91,
        "redemption_rules": [("<7天", 1.50), ("≥7天", 0.00)],
        "free_after_days": 7,
    },
    "019547": {
        "name": "招商纳斯达克100ETF联接(QDII)A",
        "daily_limit": 10,
        "direct_limit": 10,
        "buy_rate": 0.12,
        "management_fee": 0.50,
        "custody_fee": 0.15,
        "sales_fee": 0.00,
        "one_year": 27.01,
        "day_change": -0.92,
        "redemption_rules": [("<7天", 1.50), ("≥7天", 0.00)],
        "free_after_days": 7,
    },
    "019548": {
        "name": "招商纳斯达克100ETF联接(QDII)C",
        "daily_limit": 10,
        "direct_limit": 10,
        "buy_rate": 0.00,
        "management_fee": 0.50,
        "custody_fee": 0.15,
        "sales_fee": 0.40,
        "one_year": 26.52,
        "day_change": -0.92,
        "redemption_rules": [("<7天", 1.50), ("≥7天", 0.00)],
        "free_after_days": 7,
    },
    "019736": {
        "name": "宝盈纳斯达克100指数发起(QDII)A",
        "daily_limit": 10,
        "direct_limit": 10,
        "buy_rate": 0.12,
        "management_fee": 0.50,
        "custody_fee": 0.15,
        "sales_fee": 0.00,
        "one_year": 26.76,
        "day_change": -0.90,
        "redemption_rules": [("<7天", 1.50), ("≥7天", 0.00)],
        "free_after_days": 7,
    },
    "019737": {
        "name": "宝盈纳斯达克100指数发起(QDII)C",
        "daily_limit": 10,
        "direct_limit": 10,
        "buy_rate": 0.00,
        "management_fee": 0.50,
        "custody_fee": 0.15,
        "sales_fee": 0.25,
        "one_year": 26.45,
        "day_change": -0.90,
        "redemption_rules": [("<7天", 1.50), ("≥7天", 0.00)],
        "free_after_days": 7,
    },
    "019524": {
        "name": "华泰柏瑞纳斯达克100ETF联接(QDII)A",
        "daily_limit": 10,
        "direct_limit": 10,
        "buy_rate": 0.12,
        "management_fee": 0.50,
        "custody_fee": 0.15,
        "sales_fee": 0.00,
        "one_year": 26.66,
        "day_change": -0.95,
        "redemption_rules": [("<7天", 1.50), ("7-30天", 0.10), ("≥30天", 0.00)],
        "free_after_days": 30,
    },
    "022664": {
        "name": "华泰柏瑞纳斯达克100ETF联接(QDII)I",
        "daily_limit": 10,
        "direct_limit": 10,
        "buy_rate": 0.00,
        "management_fee": 0.50,
        "custody_fee": 0.15,
        "sales_fee": 0.10,
        "one_year": 26.49,
        "day_change": -0.95,
        "redemption_rules": [("<7天", 1.50), ("≥7天", 0.00)],
        "free_after_days": 7,
    },
    "019525": {
        "name": "华泰柏瑞纳斯达克100ETF联接(QDII)C",
        "daily_limit": 10,
        "direct_limit": 10,
        "buy_rate": 0.00,
        "management_fee": 0.50,
        "custody_fee": 0.15,
        "sales_fee": 0.25,
        "one_year": 26.34,
        "day_change": -0.95,
        "redemption_rules": [("<7天", 1.50), ("≥7天", 0.00)],
        "free_after_days": 7,
    },
    "018043": {
        "name": "天弘纳斯达克100指数发起(QDII)A",
        "daily_limit": 100,
        "direct_limit": 100,
        "buy_rate": 0.10,
        "management_fee": 0.50,
        "custody_fee": 0.10,
        "sales_fee": 0.00,
        "one_year": 27.54,
        "day_change": -0.95,
        "redemption_rules": [("<7天", 1.50), ("≥7天", 0.00)],
        "free_after_days": 7,
    },
    "016055": {
        "name": "博时纳斯达克100ETF发起式联接(QDII)A人民币",
        "daily_limit": 100,
        "direct_limit": 100,
        "buy_rate": 0.10,
        "management_fee": 0.50,
        "custody_fee": 0.15,
        "sales_fee": 0.00,
        "one_year": 28.11,
        "day_change": -0.96,
        "redemption_rules": [("<7天", 1.50), ("≥7天", 0.00)],
        "free_after_days": 7,
    },
    "016532": {
        "name": "嘉实纳斯达克100ETF发起联接(QDII)A人民币",
        "daily_limit": 100,
        "direct_limit": 100,
        "buy_rate": 0.10,
        "management_fee": 0.50,
        "custody_fee": 0.10,
        "sales_fee": 0.00,
        "one_year": 27.09,
        "day_change": -0.96,
        "redemption_rules": [("<7天", 1.50), ("≥7天", 0.00)],
        "free_after_days": 7,
    },
    "015299": {
        "name": "华夏纳斯达克100ETF发起式联接(QDII)A",
        "daily_limit": 100,
        "direct_limit": 100,
        "buy_rate": 0.12,
        "management_fee": 0.60,
        "custody_fee": 0.20,
        "sales_fee": 0.00,
        "one_year": 27.58,
        "day_change": -0.97,
        "redemption_rules": [("<7天", 1.50), ("≥7天", 0.00)],
        "free_after_days": 7,
    },
    "161130": {
        "name": "易方达纳斯达克100ETF联接(QDII-LOF)A人民币",
        "daily_limit": 10,
        "direct_limit": 10,
        "buy_rate": 0.12,
        "management_fee": 0.50,
        "custody_fee": 0.10,
        "sales_fee": 0.00,
        "one_year": 27.03,
        "day_change": -0.99,
        "redemption_rules": [("<7天", 1.50), ("≥7天", 0.00)],
        "free_after_days": 7,
    },
}


FALLBACK_THREE_YEAR = {
    "019441": 16.97,
    "019442": 16.91,
    "040046": 18.06,
    "014978": 18.01,
    "021778": 17.81,
    "021000": 17.27,
    "000834": 16.73,
    "008971": 16.64,
    "539001": 16.80,
    "023422": 16.72,
    "012752": 16.71,
    "018966": 16.41,
    "021773": 16.38,
    "018967": 16.29,
    "016452": 17.27,
    "016453": 17.25,
    "270042": 17.86,
    "006479": 17.81,
    "019172": 16.96,
    "019173": 16.88,
    "019547": 17.13,
    "019548": 17.01,
    "019736": 16.73,
    "019737": 16.66,
    "019524": 17.29,
    "022664": 17.27,
    "019525": 17.22,
    "018043": 17.24,
    "016055": 17.65,
    "016532": 17.81,
    "015299": 17.25,
    "161130": 17.45,
}


@dataclass
class Fund:
    code: str
    name: str
    subscription_status: str
    subscription_status_raw: str
    fund_size_billion: Optional[float]
    daily_limit: Optional[float]
    agency_limit_label: str
    direct_limit: Optional[float]
    buy_rate: Optional[float]
    management_fee: Optional[float]
    custody_fee: Optional[float]
    sales_fee: Optional[float]
    one_year: Optional[float]
    three_year: Optional[float]
    day_change: Optional[float]
    tracking_index: str
    tracking_error: Optional[float]
    tracking_avg_error: Optional[float]
    tracking_error_date: str
    redemption_rules: list[tuple[str, float]]
    free_after_days: Optional[int]
    source_notes: list[str]
    direct_limit_source: str

    @property
    def operation_fee(self) -> Optional[float]:
        if self.management_fee is None or self.custody_fee is None or self.sales_fee is None:
            return None
        return self.management_fee + self.custody_fee + self.sales_fee

    @property
    def base_annual_fee_rate(self) -> Optional[float]:
        if self.management_fee is None or self.custody_fee is None:
            return None
        return self.management_fee + self.custody_fee


def fetch_text(url: str, encoding: str = "utf-8", timeout: int = 20) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://fund.eastmoney.com/",
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return raw.decode(encoding, errors="ignore")


def fetch_direct_limit_announcements(code: str, page_size: int = 100) -> list[dict[str, str]]:
    url = (
        "https://api.fund.eastmoney.com/f10/JJGG"
        f"?fundcode={code}&pageIndex=1&pageSize={page_size}&type=0"
    )
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": f"https://fundf10.eastmoney.com/jjgg_{code}.html",
        },
    )
    with urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
    rows = payload.get("Data") or []
    candidates = []
    for row in rows:
        title = row.get("TITLE") or ""
        if not any(keyword in title for keyword in DIRECT_LIMIT_ANNOUNCEMENT_KEYWORDS):
            continue
        notice_id = row.get("ID") or ""
        candidates.append(
            {
                "code": code,
                "title": title,
                "date": row.get("PUBLISHDATEDesc") or "",
                "id": notice_id,
                "pdf_url": f"https://pdf.dfcfw.com/pdf/H2_{notice_id}_1.pdf" if notice_id else "",
            }
        )
    return candidates


def fetch_announcement_content(notice_id: str) -> dict[str, str]:
    if not notice_id:
        return {}
    url = f"https://np-cnotice-fund.eastmoney.com/api/content/ann?art_code={notice_id}&client_source=web"
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://fundf10.eastmoney.com/",
        },
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urlopen(req, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
            break
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(0.6 + attempt * 0.8)
    else:
        if last_error:
            raise last_error
        return {}
    data = payload.get("data") or {}
    content = data.get("notice_content") or ""
    content = re.sub(r"\s+", " ", content).strip()
    return {
        "notice_date": data.get("notice_date") or "",
        "notice_title": data.get("notice_title") or "",
        "content_excerpt": content[:1200],
        "attach_url": data.get("attach_url") or "",
    }


def number_or_none(value: object) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip().replace("%", "").replace(",", "")
    if text in {"", "--", "---", "None"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_limit(status: str) -> Optional[float]:
    if not status:
        return None
    match = re.search(r"上限\s*([0-9.]+)\s*万?元", status)
    if not match:
        return None
    amount = float(match.group(1))
    if "万元" in status or "万" in status[match.start() : match.end()]:
        return amount * 10000
    return amount


def normalize_subscription_status(status: str) -> str:
    if not status:
        return "未抓到"
    if "暂停申购" in status:
        return "暂停申购"
    if "限大额" in status or "限制大额" in status:
        return "限大额"
    if "开放申购" in status:
        return "开放申购"
    text = re.sub(r"[（(].*?[）)]", "", status).strip()
    return text or status


def subscription_status_rank(status: str) -> int:
    if status == "开放申购":
        return 0
    if status == "限大额":
        return 1
    if status == "暂停申购":
        return 2
    return 9


def subscription_status_class(status: str) -> str:
    if status == "开放申购":
        return "good"
    if status == "限大额":
        return "warn"
    if status == "暂停申购":
        return "bad"
    return "info"


def normalize_limit_text(value: Optional[float]) -> str:
    if value is None:
        return "未抓到"
    if value >= 10000 and value % 10000 == 0:
        return data_text(f"{int(value)}元")
    if value.is_integer():
        return data_text(f"{int(value)}元")
    return data_text(f"{value:g}元")


def fund_display_name(fund: Fund) -> str:
    return FUND_DISPLAY_LABELS.get(fund.code, fund.name.split("纳斯达克", 1)[0] or fund.name)


def fund_status(code: str) -> str:
    if code in NEW_AUTO_INVESTING_CODES:
        return "新增定投"
    if code in PAUSED_AUTO_INVESTING_CODES:
        return "暂停定投"
    if code in AUTO_INVESTING_CODES:
        return "定投中"
    if code in OWNED_CODES:
        return "已持有"
    return "候选"


def fund_status_rank(code: str) -> int:
    status = fund_status(code)
    order = {
        "新增定投": 0,
        "定投中": 1,
        "暂停定投": 2,
        "已持有": 3,
        "候选": 4,
    }
    return order.get(status, 9)


def fund_status_class(code: str) -> str:
    status = fund_status(code)
    if status in {"新增定投", "定投中"}:
        return "owned"
    if status == "暂停定投":
        return "paused"
    if status == "已持有":
        return "info"
    return "watch"


def holding_horizon(code: str, name: str) -> str:
    if re.search(r"(?:\b|人民币)A(?:\b|人民币|$)|\(QDII\)A", name):
        return "long"
    return "short"


def holding_horizon_text(value: str) -> str:
    if value == "long":
        return "长期持有"
    if value == "short":
        return "短期灵活"
    return "全部周期"


def agency_limit_text(fund: Fund) -> str:
    if fund.agency_limit_label:
        return fund.agency_limit_label
    return normalize_limit_text(fund.daily_limit)


def agency_sort_value(fund: Fund) -> str:
    if fund.daily_limit is not None:
        return sort_value(fund.daily_limit)
    if fund.agency_limit_label == "无":
        return "-1"
    return sort_value(None)


def first_json_object(text: str) -> dict:
    return json.loads(text)


def extract_table_section(page: str, title: str) -> str:
    pattern = rf"<h4 class=\"t\"><label class=\"left\">{re.escape(title)}.*?</h4>(.*?)</div></div>"
    match = re.search(pattern, page, flags=re.S)
    return match.group(1) if match else ""


def strip_tags(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def extract_fee(page: str, label: str) -> Optional[float]:
    match = re.search(rf"{label}</td>\s*<td[^>]*>\s*([0-9.]+)%", page)
    return float(match.group(1)) if match else None


def extract_buy_rate(page: str) -> Optional[float]:
    section = extract_table_section(page, "申购费率")
    if not section:
        return None
    match = re.search(r"小于[^<]+</td><td[^>]*>.*?\|\s*&nbsp;?\s*([0-9.]+)%", section, flags=re.S)
    if match:
        return float(match.group(1))
    match = re.search(r"\|\s*(?:&nbsp;)*\s*([0-9.]+)%", section, flags=re.S)
    return float(match.group(1)) if match else None


def extract_redemption_rules(page: str) -> list[tuple[str, float]]:
    section = extract_table_section(page, "赎回费率")
    rows = re.findall(r"<tr>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>([0-9.]+)%</td>\s*</tr>", section, flags=re.S)
    rules: list[tuple[str, float]] = []
    for term, rate in rows:
        text = strip_tags(term)
        text = (
            text.replace("小于", "<")
            .replace("大于等于", "≥")
            .replace("，", "-")
            .replace(" ", "")
        )
        text = re.sub(r"≥([0-9]+)天-<([0-9]+)天", r"\1-\2天", text)
        rules.append((text, float(rate)))
    return rules


def extract_tracking_data(page: str) -> dict[str, object]:
    if "年化跟踪误差" not in page:
        return {}
    table_match = re.search(
        r"跟踪指数.*?年化跟踪误差.*?同类平均跟踪误差.*?<tr>\s*"
        r"<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>",
        page,
        flags=re.S,
    )
    if not table_match:
        return {}
    date_match = re.search(r'<div class="limit-time">\s*截止至：\s*([0-9-]+)\s*</div>', page)
    return {
        "tracking_index": strip_tags(table_match.group(1)),
        "tracking_error": number_or_none(strip_tags(table_match.group(2))),
        "tracking_avg_error": number_or_none(strip_tags(table_match.group(3))),
        "tracking_error_date": date_match.group(1) if date_match else "",
    }


def free_after_days(rules: list[tuple[str, float]]) -> Optional[int]:
    for term, rate in rules:
        if rate != 0:
            continue
        match = re.search(r"≥([0-9]+)天", term)
        if match:
            return int(match.group(1))
        match = re.search(r"≥([0-9]+)年", term)
        if match:
            return int(match.group(1)) * 365
        match = re.search(r"([0-9]+)-", term)
        if match:
            return int(match.group(1))
    return None


def direct_limit_source_text(override: dict) -> str:
    source_url = override.get("source_url") or ""
    source_note = override.get("source_note") or "Codex/联网查询校准"
    effective_date = override.get("effective_date") or ""
    channel_note = override.get("channel_note") or ""
    future_note = override.get("future_note") or ""
    parts = [source_note]
    if effective_date:
        parts.append(f"生效日/公告日: {effective_date}")
    if channel_note:
        parts.append(channel_note)
    if future_note:
        parts.append(future_note)
    if source_url:
        parts.append(source_url)
    return "直销限额: " + "；".join(parts)


def fetch_fund(code: str, direct_limit_overrides: dict[str, dict]) -> Fund:
    fallback = FALLBACK[code]
    notes: list[str] = []
    values = dict(fallback)
    values["subscription_status_raw"] = ""
    values["subscription_status"] = "未抓到"
    values["fund_size_billion"] = None
    values["three_year"] = FALLBACK_THREE_YEAR.get(code)
    values["tracking_index"] = ""
    values["tracking_error"] = None
    values["tracking_avg_error"] = None
    values["tracking_error_date"] = ""
    direct_limit_source = "直销限额: 脚本内置回退值，待基金公司直销公告核验"

    override = direct_limit_overrides.get(code)
    if override:
        if not isinstance(override, dict):
            override = {"limit": override, "source_note": "Codex/联网查询校准"}
        limit_value = override.get("limit")
        parsed_limit = number_or_none(limit_value)
        if parsed_limit is not None:
            values["direct_limit"] = parsed_limit
            direct_limit_source = direct_limit_source_text(override)

    try:
        base_url = (
            "https://fundmobapi.eastmoney.com/FundMApi/FundBaseTypeInformation.ashx"
            f"?FCODE={code}&deviceid=Wap&plat=Wap&product=EFund&version=2.0.0"
        )
        base = first_json_object(fetch_text(base_url))
        data = base.get("Datas") or {}
        values["name"] = data.get("SHORTNAME") or values["name"]
        sgzt = data.get("SGZT") or ""
        values["subscription_status_raw"] = sgzt
        values["subscription_status"] = normalize_subscription_status(sgzt)
        endnav = number_or_none(data.get("ENDNAV"))
        if endnav is not None:
            values["fund_size_billion"] = round(endnav / 100000000, 2)
        values["daily_limit"] = parse_limit(sgzt) or values["daily_limit"]
        values["buy_rate"] = number_or_none(data.get("RATE")) or values["buy_rate"]
        values["one_year"] = number_or_none(data.get("SYL_1N")) or values["one_year"]
        values["three_year"] = number_or_none(data.get("SYL_3Y")) or values.get("three_year")
        values["day_change"] = number_or_none(data.get("RZDF")) or values["day_change"]
        notes.append("基础行情/限额/规模: 东方财富移动接口")
    except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        notes.append(f"基础行情/限额/规模: 回退截图校准值 ({exc.__class__.__name__})")

    try:
        fee_page = fetch_text(f"https://fundf10.eastmoney.com/jjfl_{code}.html", encoding="utf-8")
        values["management_fee"] = extract_fee(fee_page, "管理费率") or values["management_fee"]
        values["custody_fee"] = extract_fee(fee_page, "托管费率") or values["custody_fee"]
        values["sales_fee"] = extract_fee(fee_page, "销售服务费率")
        if values["sales_fee"] is None:
            values["sales_fee"] = fallback["sales_fee"]
        values["buy_rate"] = extract_buy_rate(fee_page) or values["buy_rate"]
        rules = extract_redemption_rules(fee_page)
        if rules:
            values["redemption_rules"] = rules
            values["free_after_days"] = free_after_days(rules) or values["free_after_days"]
        notes.append("费率/赎回: 天天基金基金费率页")
    except (URLError, TimeoutError, OSError) as exc:
        notes.append(f"费率/赎回: 回退截图校准值 ({exc.__class__.__name__})")

    try:
        tracking_page = fetch_text(f"https://fundf10.eastmoney.com/tsdata_{code}.html", encoding="utf-8")
        tracking_data = extract_tracking_data(tracking_page)
        if tracking_data:
            values.update(tracking_data)
            notes.append("跟踪误差: 天天基金特色数据页")
        else:
            notes.append("跟踪误差: 天天基金特色数据页未给出")
    except (URLError, TimeoutError, OSError) as exc:
        notes.append(f"跟踪误差: 未抓到 ({exc.__class__.__name__})")

    return Fund(
        code=code,
        name=values["name"],
        subscription_status=values["subscription_status"],
        subscription_status_raw=values["subscription_status_raw"],
        fund_size_billion=values["fund_size_billion"],
        daily_limit=values["daily_limit"],
        agency_limit_label=values.get("agency_limit_label") or AGENCY_LIMIT_LABELS.get(code, ""),
        direct_limit=values["direct_limit"],
        buy_rate=values["buy_rate"],
        management_fee=values["management_fee"],
        custody_fee=values["custody_fee"],
        sales_fee=values["sales_fee"],
        one_year=values["one_year"],
        three_year=values.get("three_year"),
        day_change=values["day_change"],
        tracking_index=values["tracking_index"],
        tracking_error=values["tracking_error"],
        tracking_avg_error=values["tracking_avg_error"],
        tracking_error_date=values["tracking_error_date"],
        redemption_rules=values["redemption_rules"],
        free_after_days=values["free_after_days"],
        source_notes=notes,
        direct_limit_source=direct_limit_source,
    )


def tag_class(value: Optional[float], kind: str) -> str:
    if value is None:
        return "warn"
    if kind == "limit":
        if value >= 10000:
            return "good"
        if value >= 50:
            return "info"
        return "bad"
    if kind == "fee":
        if value <= 0.65:
            return "good"
        if value <= 0.80:
            return "warn"
        return "bad"
    if kind == "free_days":
        if value <= 7:
            return "good"
        if value <= 90:
            return "warn"
        return "bad"
    return "info"


def fmt_percent(value: Optional[float], digits: int = 2) -> str:
    if value is None:
        return "未抓到"
    sign = "+" if value > 0 else ""
    return data_text(f"{sign}{value:.{digits}f}%")


def fmt_fee(value: Optional[float]) -> str:
    if value is None:
        return "未抓到"
    return data_text(f"{value:.2f}%/年")


def fee_project_html(fund: Fund) -> str:
    sales_note = "" if fund.sales_fee == 0 else " · 按日计提"
    return (
        '<div class="fee-detail">'
        f"<span>管理费率 {fmt_fee(fund.management_fee)}</span>"
        f"<span>托管费率 {fmt_fee(fund.custody_fee)}</span>"
        f"<span>销售服务费率 {fmt_fee(fund.sales_fee)}{sales_note}</span>"
        "</div>"
    )


def tracking_error_html(fund: Fund) -> str:
    if fund.tracking_error is None:
        return '<span class="muted-cell">未抓到</span>'
    avg_text = fmt_percent(fund.tracking_avg_error) if fund.tracking_avg_error is not None else "同类未抓到"
    return (
        '<div class="tracking-detail">'
        f'<strong>{fmt_percent(fund.tracking_error)}</strong>'
        f"<span>同类均值 {avg_text}</span>"
        "</div>"
    )


def fmt_buy_rate(value: Optional[float]) -> str:
    if value is None:
        return "未抓到"
    return data_text(f"{value:.3f}%")


def fmt_size_billion(value: Optional[float]) -> str:
    if value is None:
        return '<span class="muted-cell">未抓到</span>'
    return data_text(f"{value:.1f}亿")


def data_text(value: object) -> str:
    return f'<span class="data-text">{html.escape(str(value))}</span>'


def name_code_text(label: str, code: str) -> str:
    return f"{html.escape(label)} {data_text(code)}"


def fmt_yuan(value: float) -> str:
    if float(value).is_integer():
        return data_text(f"{int(value)}元")
    return data_text(f"{value:.2f}元")


def fund_amount_sort_key(funds_by_code: dict[str, Fund], item: tuple[str, float]) -> tuple[float, str]:
    code, amount = item
    label = fund_display_name(funds_by_code[code]) if code in funds_by_code else code
    return (-amount, label)


def position_plan_html(code: str) -> str:
    holding_amount = HOLDING_AMOUNTS.get(code, 0)
    active_amount = AUTO_INVEST_AMOUNTS.get(code, 0)
    paused_amount = PAUSED_AUTO_INVEST_AMOUNTS.get(code, 0)
    holding = (
        f'<span class="position-line"><em>持有</em><strong>{fmt_yuan(holding_amount)}</strong></span>'
        if holding_amount
        else '<span class="position-line muted-line"><em>持有</em><strong>0元</strong></span>'
    )
    if active_amount:
        invest = f'<span class="position-line"><em>定投</em><strong>{fmt_yuan(active_amount)} / 期</strong></span>'
    elif paused_amount:
        invest = f'<span class="position-line paused-line"><em>暂停</em><strong>{fmt_yuan(paused_amount)} / 期</strong></span>'
    else:
        invest = '<span class="position-line muted-line"><em>定投</em><strong>未设置</strong></span>'
    return f'<div class="position-plan">{holding}{invest}</div>'


def sort_value(value: Optional[float], default: float = 999999) -> str:
    if value is None:
        return str(default)
    return f"{value:.6f}"


def normalize_metric(value: Optional[float], values: list[float], reverse: bool = False) -> float:
    if value is None or not values:
        return 0.0
    low = min(values)
    high = max(values)
    if high == low:
        score = 0.5
    else:
        score = (value - low) / (high - low)
        score = max(0.0, min(1.0, score))
    return 1.0 - score if reverse else score


def log_limit_value(value: Optional[float]) -> Optional[float]:
    if value is None or value <= 0:
        return None
    return math.log10(max(value, 1))


def score_context(funds: list[Fund]) -> dict[str, list[float]]:
    def present(values: list[Optional[float]]) -> list[float]:
        return [value for value in values if value is not None]

    return {
        "three_year": present([fund.three_year for fund in funds]),
        "one_year": present([fund.one_year for fund in funds]),
        "tracking_error": present([fund.tracking_error for fund in funds]),
        "base_fee": present([fund.base_annual_fee_rate for fund in funds]),
        "fund_size": present([log_limit_value(fund.fund_size_billion) for fund in funds]),
        "buy_rate": present([fund.buy_rate for fund in funds]),
        "free_days": present([float(fund.free_after_days) if fund.free_after_days is not None else None for fund in funds]),
    }


def investing_score(fund: Fund, context: dict[str, list[float]]) -> float:
    fund_size_log = log_limit_value(fund.fund_size_billion)
    score = (
        SCORING_WEIGHTS["three_year"] * normalize_metric(fund.three_year, context["three_year"])
        + SCORING_WEIGHTS["one_year"] * normalize_metric(fund.one_year, context["one_year"])
        + SCORING_WEIGHTS["tracking_error"] * normalize_metric(fund.tracking_error, context["tracking_error"], reverse=True)
        + SCORING_WEIGHTS["base_fee"] * normalize_metric(fund.base_annual_fee_rate, context["base_fee"], reverse=True)
        + SCORING_WEIGHTS["fund_size"] * normalize_metric(fund_size_log, context["fund_size"])
        + SCORING_WEIGHTS["buy_rate"] * normalize_metric(fund.buy_rate, context["buy_rate"], reverse=True)
        + SCORING_WEIGHTS["free_days"] * normalize_metric(float(fund.free_after_days) if fund.free_after_days is not None else None, context["free_days"], reverse=True)
    )
    return round(score * 100, 1)


def tier_for_rank(rank: int, total: int) -> str:
    percentile = (rank - 0.5) / total
    if percentile <= 0.10:
        return "S"
    if percentile <= 0.325:
        return "A"
    if percentile <= 0.675:
        return "B"
    if percentile <= 0.90:
        return "C"
    return "D"


def tier_class(tier: str) -> str:
    return {
        "S": "tier-s",
        "A": "tier-a",
        "B": "tier-b",
        "C": "tier-c",
        "D": "tier-d",
    }.get(tier, "tier-c")


def score_cards(funds: list[Fund]) -> dict[str, dict[str, object]]:
    context = score_context(funds)
    scored = sorted(
        [(investing_score(fund, context), fund.code) for fund in funds],
        key=lambda item: item[0],
        reverse=True,
    )
    cards: dict[str, dict[str, object]] = {}
    total = len(scored)
    for rank, (score, code) in enumerate(scored, 1):
        tier = tier_for_rank(rank, total)
        cards[code] = {"rank": rank, "score": score, "tier": tier}
    return cards


def rule_html(rules: list[tuple[str, float]]) -> str:
    parts = []
    for term, rate in rules:
        rate_text = data_text(f"{rate:g}%")
        parts.append(
            f'<div class="rule-line"><span>{html.escape(term)}</span><strong>{rate_text}</strong></div>'
        )
    return '<div class="sell-rules">' + "".join(parts) + "</div>"


def scoring_rule_rows() -> str:
    rows = []
    for rule in SCORING_RULES:
        rows.append(
            f"""
            <tr>
              <td data-label="指标">{html.escape(rule["label"])}</td>
              <td class="num" data-label="权重" data-sort-value="{rule["weight"]:.6f}">{rule["weight"] * 100:.0f}%</td>
              <td data-label="方向">{html.escape(rule["direction"])}</td>
              <td data-label="计算口径">{html.escape(rule["method"])}</td>
              <td data-label="纳入评级的理由">{html.escape(rule["reason"])}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def fund_record_name(funds_by_code: dict[str, Fund], code: str) -> str:
    fund = funds_by_code.get(code)
    if not fund:
        return data_text(code)
    return name_code_text(fund_display_name(fund), code)


def fund_record_rating(cards: dict[str, dict[str, object]], code: str) -> str:
    card = cards.get(code)
    if not card:
        return '<span class="muted-cell">-</span>'
    tier = str(card["tier"])
    score = float(card["score"])
    return f'<span class="tier-pill portfolio-tier {tier_class(tier)}"><strong>{tier}</strong><span>{data_text(f"{score:.1f}")}</span></span>'


def holding_record_rows(funds_by_code: dict[str, Fund], cards: dict[str, dict[str, object]]) -> str:
    rows = []
    sorted_holdings = sorted(HOLDING_AMOUNTS.items(), key=lambda item: fund_amount_sort_key(funds_by_code, item))
    for index, (code, amount) in enumerate(sorted_holdings, start=1):
        rows.append(
            f"""
            <tr data-code="{html.escape(code)}">
              <td class="num record-index" data-label="序号">{data_text(str(index))}</td>
              <td data-label="基金">{fund_record_name(funds_by_code, code)}</td>
              <td class="num" data-label="评级">{fund_record_rating(cards, code)}</td>
              <td class="num editable-amount" data-label="持有金额" data-field="holding" data-sort-value="{amount:.6f}" tabindex="0" role="button" title="点击修改持有金额">{fmt_yuan(amount)}</td>
              <td class="editable-status" data-label="定投状态" data-field="status" tabindex="0" role="button" title="点击选择定投状态"><span class="tag {fund_status_class(code)}">{fund_status(code)}</span></td>
            </tr>
            """
        )
    return "\n".join(rows)


def auto_invest_record_rows(funds_by_code: dict[str, Fund], cards: dict[str, dict[str, object]]) -> str:
    rows = []
    merged_codes = sorted(
        set(AUTO_INVEST_AMOUNTS) | set(PAUSED_AUTO_INVEST_AMOUNTS),
        key=lambda code: (
            0 if code in AUTO_INVEST_AMOUNTS else 1,
            -(AUTO_INVEST_AMOUNTS.get(code, PAUSED_AUTO_INVEST_AMOUNTS.get(code, 0))),
            fund_display_name(funds_by_code[code]) if code in funds_by_code else code,
        ),
    )
    for index, code in enumerate(merged_codes, start=1):
        active_amount = AUTO_INVEST_AMOUNTS.get(code, 0)
        paused_amount = PAUSED_AUTO_INVEST_AMOUNTS.get(code, 0)
        holding_amount = HOLDING_AMOUNTS.get(code, 0)
        status = "定投中" if active_amount else "暂停定投"
        amount = active_amount or paused_amount
        rows.append(
            f"""
            <tr data-code="{html.escape(code)}">
              <td class="num record-index" data-label="序号">{data_text(str(index))}</td>
              <td data-label="基金">{fund_record_name(funds_by_code, code)}</td>
              <td class="num" data-label="评级">{fund_record_rating(cards, code)}</td>
              <td class="editable-status" data-label="状态" data-field="status" tabindex="0" role="button" title="点击选择定投状态"><span class="tag {fund_status_class(code)}">{status}</span></td>
              <td class="num editable-amount" data-label="金额" data-field="plan_amount" data-sort-value="{amount:.6f}" tabindex="0" role="button" title="点击修改定投金额">{fmt_yuan(amount)} / 期</td>
              <td class="num editable-amount" data-label="当前持有" data-field="holding" data-sort-value="{holding_amount:.6f}" tabindex="0" role="button" title="点击修改持有金额">{fmt_yuan(holding_amount)}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def tracking_number(value: object, suffix: str = "") -> str:
    if value is None or value == "":
        return '<span class="muted-cell">--</span>'
    try:
        number = float(value)
    except (TypeError, ValueError):
        return data_text(str(value))
    if number.is_integer():
        text = f"{int(number)}{suffix}"
    else:
        text = f"{number:.2f}{suffix}"
    return data_text(text)


def tracking_percent(value: object) -> str:
    if value is None or value == "":
        return '<span class="muted-cell">--</span>'
    try:
        number = float(value)
    except (TypeError, ValueError):
        return data_text(str(value))
    sign = "+" if number > 0 else ""
    return data_text(f"{sign}{number:.2f}%")


def tracking_value(value: object) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def tracking_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def tracking_amount_label(value: object) -> str:
    number = tracking_float(value)
    if number.is_integer():
        return f"{int(number)}"
    return f"{number:.2f}"


def tracking_date_label(record: dict[str, object]) -> str:
    return str(record.get("date") or record.get("recorded_at") or "-")


def tracking_svg_axis_value(value: float, suffix: str = "") -> str:
    if abs(value) >= 10000:
        return f"{value / 10000:.1f}万{suffix}"
    if float(value).is_integer():
        return f"{int(value)}{suffix}"
    return f"{value:.1f}{suffix}"


def tracking_series_points(records: list[dict[str, object]], key: str) -> list[Optional[float]]:
    return [tracking_value(record.get(key)) for record in records]


def tracking_path(points: list[Optional[float]], low: float, high: float, width: int, height: int) -> str:
    left, right, top, bottom = 46, 18, 18, 32
    chart_w = width - left - right
    chart_h = height - top - bottom
    count = len(points)
    parts = []
    for index, value in enumerate(points):
        if value is None:
            continue
        x = left + (chart_w / 2 if count <= 1 else chart_w * index / (count - 1))
        y = top + chart_h * (1 - ((value - low) / (high - low) if high != low else 0.5))
        parts.append((x, y))
    if not parts:
        return ""
    if len(parts) == 1:
        x, y = parts[0]
        return f"M {x:.2f} {y:.2f}"
    return " ".join(
        f"{'M' if index == 0 else 'L'} {x:.2f} {y:.2f}"
        for index, (x, y) in enumerate(parts)
    )


def tracking_point_circles(points: list[Optional[float]], low: float, high: float, width: int, height: int, class_name: str) -> str:
    left, right, top, bottom = 46, 18, 18, 32
    chart_w = width - left - right
    chart_h = height - top - bottom
    count = len(points)
    circles = []
    for index, value in enumerate(points):
        if value is None:
            continue
        x = left + (chart_w / 2 if count <= 1 else chart_w * index / (count - 1))
        y = top + chart_h * (1 - ((value - low) / (high - low) if high != low else 0.5))
        circles.append(f'<circle class="{class_name}" cx="{x:.2f}" cy="{y:.2f}" r="3.2" />')
    return "".join(circles)


def tracking_line_chart_svg(
    records: list[dict[str, object]],
    series: list[dict[str, str]],
    empty_label: str,
    percent_axis: bool = False,
) -> str:
    width, height = 640, 220
    left, right, top, bottom = 46, 18, 18, 32
    chart_w = width - left - right
    chart_h = height - top - bottom
    records = records[-24:] or []
    series_values = [(item, tracking_series_points(records, item["key"])) for item in series]
    all_values = [value for _, values in series_values for value in values if value is not None]
    if not all_values:
        return f"""
        <svg class="tracking-chart-svg" viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(empty_label)}">
          <rect class="chart-bg" x="0" y="0" width="{width}" height="{height}" />
          <line class="chart-grid" x1="{left}" y1="{top + chart_h / 2:.2f}" x2="{left + chart_w}" y2="{top + chart_h / 2:.2f}" />
          <text class="chart-empty" x="{width / 2:.2f}" y="{height / 2:.2f}" text-anchor="middle">{html.escape(empty_label)}</text>
        </svg>
        """
    low = min(all_values)
    high = max(all_values)
    if low == high:
        pad = max(abs(low) * 0.08, 10 if not percent_axis else 1)
        low -= pad
        high += pad
    grid_lines = []
    for step in range(3):
        y = top + chart_h * step / 2
        value = high - (high - low) * step / 2
        label = tracking_svg_axis_value(value, "%" if percent_axis else "")
        grid_lines.append(
            f'<line class="chart-grid" x1="{left}" y1="{y:.2f}" x2="{left + chart_w}" y2="{y:.2f}" />'
            f'<text class="chart-axis" x="{left - 8}" y="{y + 4:.2f}" text-anchor="end">{html.escape(label)}</text>'
        )
    if records:
        first_label = tracking_date_label(records[0])
        last_label = tracking_date_label(records[-1])
    else:
        first_label = last_label = "-"
    paths = []
    legends = []
    for index, (item, values) in enumerate(series_values):
        path = tracking_path(values, low, high, width, height)
        if path:
            class_name = f"chart-series chart-series-{index + 1}"
            point_class = f"chart-point chart-point-{index + 1}"
            paths.append(f'<path class="{class_name}" d="{path}" />')
            paths.append(tracking_point_circles(values, low, high, width, height, point_class))
            legends.append(
                f'<span class="chart-legend-item"><i class="legend-dot legend-dot-{index + 1}"></i>{html.escape(item["label"])}</span>'
            )
    legend_html = f'<foreignObject x="{left}" y="0" width="{chart_w}" height="24"><div xmlns="http://www.w3.org/1999/xhtml" class="chart-legend">{"".join(legends)}</div></foreignObject>'
    return f"""
    <svg class="tracking-chart-svg" viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(series[0]["label"])}">
      <rect class="chart-bg" x="0" y="0" width="{width}" height="{height}" />
      {''.join(grid_lines)}
      {legend_html}
      {''.join(paths)}
      <text class="chart-axis" x="{left}" y="{height - 9}" text-anchor="start">{html.escape(first_label)}</text>
      <text class="chart-axis" x="{left + chart_w}" y="{height - 9}" text-anchor="end">{html.escape(last_label)}</text>
    </svg>
    """


def tracking_asset_chart_svg(payload: dict[str, object]) -> str:
    records = tracking_records(payload)
    return tracking_line_chart_svg(
        records,
        [
            {"key": "holding_total", "label": "持有记录"},
            {"key": "market_value", "label": "市值"},
        ],
        "等待更多资产记录",
    )


def tracking_return_chart_svg(payload: dict[str, object]) -> str:
    records = tracking_records(payload)
    values = [tracking_value(record.get("return_rate")) for record in records]
    if any(value is not None for value in values):
        return tracking_line_chart_svg(
            records,
            [{"key": "return_rate", "label": "收益率"}],
            "等待收益率记录",
            percent_axis=True,
        )
    return tracking_line_chart_svg(
        records,
        [{"key": "profit", "label": "收益"}],
        "等待收益记录",
    )


def tracking_allocation_html(
    funds: list[Fund],
    cards: dict[str, dict[str, object]],
    payload: dict[str, object],
) -> str:
    latest = latest_tracking_record(payload)
    tracked_funds = latest.get("funds") if isinstance(latest.get("funds"), dict) else {}
    funds_by_code = {fund.code: fund for fund in funds}
    items = []
    for fund in tracking_visible_funds(funds, cards, payload):
        item = tracked_funds.get(fund.code) if isinstance(tracked_funds, dict) else None
        if not isinstance(item, dict):
            item = {}
        amount = tracking_float(item.get("holding_amount", HOLDING_AMOUNTS.get(fund.code, 0)))
        if amount <= 0:
            continue
        items.append((fund.code, amount))
    total = sum(amount for _, amount in items)
    if total <= 0:
        return '<div class="allocation-empty">暂无持仓金额</div>'
    rows = []
    for code, amount in sorted(items, key=lambda item: item[1], reverse=True):
        share = amount / total * 100
        tier = str(cards.get(code, {}).get("tier", "-"))
        rows.append(
            f"""
            <div class="allocation-row">
              <div class="allocation-head">
                <span>{fund_record_name(funds_by_code, code)}</span>
                <strong>{tracking_amount_label(amount)}元 · {share:.1f}%</strong>
              </div>
              <div class="allocation-track"><span class="{tier_class(tier)}" style="width: {share:.2f}%"></span></div>
            </div>
            """
        )
    return "\n".join(rows)


def default_tracking_funds(funds: list[Fund], cards: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    items: dict[str, dict[str, object]] = {}
    for fund in funds:
        code = fund.code
        card = cards.get(code, {})
        items[code] = {
            "name": fund_display_name(fund),
            "rating": card.get("tier"),
            "score": card.get("score"),
            "holding_amount": HOLDING_AMOUNTS.get(code, 0),
            "active_auto_invest_amount": AUTO_INVEST_AMOUNTS.get(code, 0),
            "paused_auto_invest_amount": PAUSED_AUTO_INVEST_AMOUNTS.get(code, 0),
            "market_value": None,
            "cost_basis": None,
            "profit": None,
            "return_rate": None,
        }
    return items


def default_tracking_record(funds: list[Fund], cards: dict[str, dict[str, object]]) -> dict[str, object]:
    now = now_beijing()
    return {
        "date": now.strftime("%Y-%m-%d"),
        "recorded_at": now.isoformat(timespec="seconds"),
        "holding_total": sum(HOLDING_AMOUNTS.values()),
        "active_auto_invest_total": sum(AUTO_INVEST_AMOUNTS.values()),
        "paused_auto_invest_total": sum(PAUSED_AUTO_INVEST_AMOUNTS.values()),
        "market_value": None,
        "cost_basis": None,
        "profit": None,
        "return_rate": None,
        "funds": default_tracking_funds(funds, cards),
        "note": "自动刷新基线",
    }


def merge_tracking_fund_record(existing: object, fresh: dict[str, object]) -> dict[str, object]:
    merged = dict(fresh)
    if isinstance(existing, dict):
        for field in PERSONAL_TRACKING_FIELDS:
            if existing.get(field) is not None:
                merged[field] = existing.get(field)
    return merged


def merge_tracking_record(existing: dict[str, object], fresh: dict[str, object]) -> dict[str, object]:
    merged = dict(fresh)
    for field in PERSONAL_TRACKING_FIELDS:
        if existing.get(field) is not None:
            merged[field] = existing.get(field)
    existing_funds = existing.get("funds") if isinstance(existing.get("funds"), dict) else {}
    fresh_funds = fresh.get("funds") if isinstance(fresh.get("funds"), dict) else {}
    merged_funds: dict[str, dict[str, object]] = {}
    for code, fresh_item in fresh_funds.items():
        if not isinstance(fresh_item, dict):
            continue
        existing_item = existing_funds.get(code) if isinstance(existing_funds, dict) else None
        merged_funds[code] = merge_tracking_fund_record(existing_item, fresh_item)
    if isinstance(existing_funds, dict):
        for code, existing_item in existing_funds.items():
            if code not in merged_funds and isinstance(existing_item, dict):
                merged_funds[code] = existing_item
    merged["funds"] = merged_funds
    existing_note = existing.get("note")
    if isinstance(existing_note, str) and existing_note.strip() and existing_note != "初始追踪记录":
        merged["note"] = existing_note
    else:
        merged["note"] = "当日自动刷新"
    return merged


def tracking_record_date(record: object) -> str:
    if not isinstance(record, dict):
        return ""
    value = record.get("date") or record.get("recorded_at")
    if not value:
        return ""
    return str(value)[:10]


def normalize_tracking_records(records: object) -> list[dict[str, object]]:
    if not isinstance(records, list):
        return []
    normalized: list[dict[str, object]] = []
    seen: dict[str, int] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        date_key = tracking_record_date(record)
        if date_key and date_key in seen:
            normalized[seen[date_key]] = merge_tracking_record(normalized[seen[date_key]], record)
        else:
            if date_key:
                seen[date_key] = len(normalized)
            normalized.append(record)
    return sorted(normalized, key=lambda item: tracking_record_date(item) or str(item.get("recorded_at") or ""))


def ensure_tracking_payload(path: Path, funds: list[Fund], cards: dict[str, dict[str, object]]) -> dict[str, object]:
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            payload = {}
    else:
        payload = {}

    if not isinstance(payload, dict):
        payload = {}
    records = normalize_tracking_records(payload.get("records"))
    fresh = default_tracking_record(funds, cards)
    today = str(fresh["date"])
    if not records:
        records = [fresh]
    else:
        updated = False
        for index, record in enumerate(records):
            if tracking_record_date(record) == today:
                records[index] = merge_tracking_record(record, fresh)
                updated = True
                break
        if not updated:
            records.append(fresh)
        records = normalize_tracking_records(records)
    payload = {
        "schema_version": TRACKING_SCHEMA_VERSION,
        "records": records,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def load_tracking_payload(path: Path, funds: list[Fund], cards: dict[str, dict[str, object]]) -> dict[str, object]:
    if not path.exists():
        return {"schema_version": TRACKING_SCHEMA_VERSION, "records": [default_tracking_record(funds, cards)]}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {"schema_version": TRACKING_SCHEMA_VERSION, "records": [default_tracking_record(funds, cards)]}
    if not isinstance(payload, dict):
        return {"schema_version": TRACKING_SCHEMA_VERSION, "records": [default_tracking_record(funds, cards)]}
    records = normalize_tracking_records(payload.get("records"))
    if not records:
        payload["records"] = [default_tracking_record(funds, cards)]
    else:
        payload["records"] = records
    return payload


def tracking_records(payload: dict[str, object]) -> list[dict[str, object]]:
    records = payload.get("records")
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


def latest_tracking_record(payload: dict[str, object]) -> dict[str, object]:
    records = tracking_records(payload)
    if not records:
        return {}
    return records[-1]


def build_source_health(funds: list[Fund]) -> dict[str, object]:
    checks = {
        "base_data": {
            "label": "基础行情/限额/规模",
            "success_marker": "基础行情/限额/规模: 东方财富移动接口",
        },
        "fee_data": {
            "label": "费率/赎回",
            "success_marker": "费率/赎回: 天天基金基金费率页",
        },
        "tracking_error": {
            "label": "跟踪误差",
            "success_marker": "跟踪误差: 天天基金特色数据页",
        },
    }
    payload: dict[str, object] = {
        "fund_count": len(funds),
        "checks": {},
    }
    check_results: dict[str, dict[str, object]] = {}
    for key, config in checks.items():
        marker = str(config["success_marker"])
        failed_codes = [
            fund.code
            for fund in funds
            if marker not in fund.source_notes
        ]
        success_count = len(funds) - len(failed_codes)
        check_results[key] = {
            "label": config["label"],
            "success_count": success_count,
            "required_success_count": len(funds),
            "failed_codes": failed_codes,
        }
    payload["checks"] = check_results
    return payload


def tracking_snapshot_rows(payload: dict[str, object]) -> str:
    rows = []
    records = list(reversed(tracking_records(payload)))
    if not records:
        return '<tr><td colspan="7" class="muted-cell">暂无追踪快照</td></tr>'
    for index, record in enumerate(records, start=1):
        date = str(record.get("date") or record.get("recorded_at") or "-")
        rows.append(
            f"""
            <tr>
              <td class="num record-index" data-label="序号">{data_text(str(index))}</td>
              <td data-label="日期">{html.escape(date)}</td>
              <td class="num" data-label="持有">{tracking_number(record.get("holding_total"), "元")}</td>
              <td class="num" data-label="定投中">{tracking_number(record.get("active_auto_invest_total"), "元/期")}</td>
              <td class="num" data-label="市值">{tracking_number(record.get("market_value"), "元")}</td>
              <td class="num" data-label="收益">{tracking_number(record.get("profit"), "元")}</td>
              <td class="num" data-label="收益率">{tracking_percent(record.get("return_rate"))}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def tracking_record_year(record: dict[str, object]) -> str:
    label = tracking_date_label(record)
    match = re.match(r"(\d{4})", label)
    return match.group(1) if match else "未知"


def tracking_record_span_label(payload: dict[str, object]) -> str:
    records = tracking_records(payload)
    if not records:
        return data_text("--")
    first = tracking_date_label(records[0])
    latest = tracking_date_label(records[-1])
    return data_text(first if first == latest else f"{first} 至 {latest}")


def tracking_record_year_count(payload: dict[str, object]) -> int:
    return len({tracking_record_year(record) for record in tracking_records(payload)})


def tracking_delta_number(latest: object, first: object, suffix: str = "") -> str:
    latest_value = tracking_value(latest)
    first_value = tracking_value(first)
    if latest_value is None or first_value is None:
        return '<span class="muted-cell">--</span>'
    delta = latest_value - first_value
    sign = "+" if delta > 0 else ""
    if delta.is_integer():
        text = f"{sign}{int(delta)}{suffix}"
    else:
        text = f"{sign}{delta:.2f}{suffix}"
    return data_text(text)


def tracking_year_summary_rows(payload: dict[str, object]) -> str:
    records = sorted(tracking_records(payload), key=tracking_date_label)
    if not records:
        return '<tr><td colspan="9" class="muted-cell">暂无年度记录</td></tr>'
    buckets: dict[str, list[dict[str, object]]] = {}
    for record in records:
        buckets.setdefault(tracking_record_year(record), []).append(record)
    rows = []
    for year, year_records in sorted(buckets.items(), reverse=True):
        first = year_records[0]
        latest = year_records[-1]
        rows.append(
            f"""
            <tr>
              <td class="num" data-label="年份">{data_text(year)}</td>
              <td class="num" data-label="记录">{data_text(str(len(year_records)))}</td>
              <td data-label="首条">{html.escape(tracking_date_label(first))}</td>
              <td data-label="末条">{html.escape(tracking_date_label(latest))}</td>
              <td class="num" data-label="持有变化">{tracking_delta_number(latest.get("holding_total"), first.get("holding_total"), "元")}</td>
              <td class="num" data-label="期末持有">{tracking_number(latest.get("holding_total"), "元")}</td>
              <td class="num" data-label="期末市值">{tracking_number(latest.get("market_value"), "元")}</td>
              <td class="num" data-label="期末收益">{tracking_number(latest.get("profit"), "元")}</td>
              <td class="num" data-label="收益率">{tracking_percent(latest.get("return_rate"))}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def tracking_visible_funds(
    funds: list[Fund],
    cards: dict[str, dict[str, object]],
    payload: dict[str, object],
) -> list[Fund]:
    latest = latest_tracking_record(payload)
    tracked_funds = latest.get("funds") if isinstance(latest.get("funds"), dict) else {}
    visible = []
    for fund in funds:
        item = tracked_funds.get(fund.code) if isinstance(tracked_funds, dict) else None
        if not isinstance(item, dict):
            item = {}
        holding_amount = tracking_float(item.get("holding_amount", HOLDING_AMOUNTS.get(fund.code, 0)))
        active_amount = tracking_float(item.get("active_auto_invest_amount", AUTO_INVEST_AMOUNTS.get(fund.code, 0)))
        paused_amount = tracking_float(item.get("paused_auto_invest_amount", PAUSED_AUTO_INVEST_AMOUNTS.get(fund.code, 0)))
        has_return_record = any(item.get(key) is not None for key in ("market_value", "cost_basis", "profit", "return_rate"))
        if holding_amount > 0 or active_amount > 0 or paused_amount > 0 or has_return_record:
            visible.append(fund)
    return sorted(
        visible,
        key=lambda fund: (
            -HOLDING_AMOUNTS.get(fund.code, 0),
            -(AUTO_INVEST_AMOUNTS.get(fund.code, 0) or PAUSED_AUTO_INVEST_AMOUNTS.get(fund.code, 0)),
            int(cards.get(fund.code, {}).get("rank", 999)),
        ),
    )


def tracking_fund_rows(
    funds: list[Fund],
    cards: dict[str, dict[str, object]],
    payload: dict[str, object],
) -> str:
    latest = latest_tracking_record(payload)
    tracked_funds = latest.get("funds") if isinstance(latest.get("funds"), dict) else {}
    rows = []
    funds_by_code = {fund.code: fund for fund in funds}
    ordered = tracking_visible_funds(funds, cards, payload)
    for index, fund in enumerate(ordered, start=1):
        item = tracked_funds.get(fund.code) if isinstance(tracked_funds, dict) else None
        if not isinstance(item, dict):
            item = {}
        holding_amount = item.get("holding_amount", HOLDING_AMOUNTS.get(fund.code, 0))
        active_amount = item.get("active_auto_invest_amount", AUTO_INVEST_AMOUNTS.get(fund.code, 0))
        paused_amount = item.get("paused_auto_invest_amount", PAUSED_AUTO_INVEST_AMOUNTS.get(fund.code, 0))
        active_number = tracking_float(active_amount)
        paused_number = tracking_float(paused_amount)
        plan_text = "无"
        if active_number > 0:
            plan_text = f"{tracking_amount_label(active_number)}元/期"
        elif paused_number > 0:
            plan_text = f"暂停 {tracking_amount_label(paused_number)}元/期"
        rows.append(
            f"""
            <tr data-code="{html.escape(fund.code)}">
              <td class="num record-index" data-label="序号">{data_text(str(index))}</td>
              <td data-label="基金">{fund_record_name(funds_by_code, fund.code)}</td>
              <td class="num" data-label="评级">{fund_record_rating(cards, fund.code)}</td>
              <td class="num" data-label="持有">{tracking_number(holding_amount, "元")}</td>
              <td class="num" data-label="定投">{data_text(plan_text)}</td>
              <td class="num" data-label="市值">{tracking_number(item.get("market_value"), "元")}</td>
              <td class="num" data-label="收益">{tracking_number(item.get("profit"), "元")}</td>
              <td class="num" data-label="收益率">{tracking_percent(item.get("return_rate"))}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def tracking_path_html(path: Path) -> str:
    return html.escape(str(path))


def main_rows(funds: list[Fund]) -> str:
    rows = []
    cards = score_cards(funds)
    for index, fund in enumerate(funds, 1):
        base_fee = fund.base_annual_fee_rate
        status = fund_status(fund.code)
        status_class = fund_status_class(fund.code)
        card = cards[fund.code]
        tier = str(card["tier"])
        score = float(card["score"])
        rank = int(card["rank"])
        holding_amount = HOLDING_AMOUNTS.get(fund.code, 0)
        active_amount = AUTO_INVEST_AMOUNTS.get(fund.code, 0)
        paused_amount = PAUSED_AUTO_INVEST_AMOUNTS.get(fund.code, 0)
        plan_sort_value = holding_amount * 1000000 + active_amount * 1000 + paused_amount
        rows.append(
            f"""
            <tr class="tier-row tier-{tier.lower()}-row" data-status="{html.escape(status)}" data-subscription-status="{html.escape(fund.subscription_status)}" data-tier="{tier}" data-code="{fund.code}" data-fund-label="{html.escape(fund_display_name(fund))}" data-score="{score:.1f}" data-holding-amount="{holding_amount:.2f}" data-auto-invest-amount="{active_amount:.2f}" data-paused-auto-invest-amount="{paused_amount:.2f}" data-agency-limit="{sort_value(fund.daily_limit, -1)}" data-direct-limit="{sort_value(fund.direct_limit, -1)}" data-agency-limit-text="{html.escape(strip_tags(agency_limit_text(fund)))}" data-direct-limit-text="{html.escape(strip_tags(normalize_limit_text(fund.direct_limit)))}">
              <td class="num row-rank">{data_text(index)}</td>
              <td class="num" data-sort-value="{1000 - rank}"><span class="tier-pill {tier_class(tier)}"><strong>{tier}</strong><span>{data_text(f"{score:.1f}")}</span></span></td>
              <td class="fund-cell" data-sort-value="{html.escape(fund.name)} {fund.code}">
                <div class="fund">
                  <span class="fund-name">{html.escape(fund.name)}</span>
                  <span class="code">{data_text(fund.code)}</span>
                </div>
              </td>
              <td data-sort-value="{plan_sort_value:.6f}">{position_plan_html(fund.code)}</td>
              <td class="num" data-sort-value="{sort_value(fund.three_year)}">{fmt_percent(fund.three_year)}</td>
              <td class="num" data-sort-value="{sort_value(fund.one_year)}">{fmt_percent(fund.one_year)}</td>
              <td data-sort-value="{sort_value(fund.tracking_error)}">{tracking_error_html(fund)}</td>
              <td class="num" data-sort-value="{sort_value(base_fee)}"><span class="tag {tag_class(base_fee, 'fee')}">{fmt_fee(base_fee)}</span></td>
              <td class="num" data-sort-value="{sort_value(fund.fund_size_billion)}">{fmt_size_billion(fund.fund_size_billion)}</td>
              <td class="num" data-sort-value="{sort_value(fund.buy_rate)}">{fmt_buy_rate(fund.buy_rate)}</td>
              <td data-sort-value="{sort_value(fund.free_after_days)}"><span class="tag {tag_class(fund.free_after_days, 'free_days')}">满{data_text(fund.free_after_days) if fund.free_after_days is not None else '未知'}天</span></td>
              <td class="num" data-sort-value="{subscription_status_rank(fund.subscription_status)}"><span class="tag {subscription_status_class(fund.subscription_status)}">{html.escape(fund.subscription_status)}</span></td>
              <td class="num" data-sort-value="{agency_sort_value(fund)}"><span class="tag {tag_class(fund.daily_limit, 'limit')}">{agency_limit_text(fund)}</span></td>
              <td class="num" data-sort-value="{sort_value(fund.direct_limit)}"><span class="tag {tag_class(fund.direct_limit, 'limit')}">{normalize_limit_text(fund.direct_limit)}</span></td>
              <td data-sort-value="{sort_value(fund.sales_fee)}">{fee_project_html(fund)}</td>
              <td data-sort-value="{sort_value(fund.free_after_days)}">{rule_html(fund.redemption_rules)}</td>
              <td class="num" data-sort-value="{sort_value(fund.day_change, 0)}">{fmt_percent(fund.day_change)}</td>
              <td data-sort-value="{fund_status_rank(fund.code)}"><span class="tag {status_class}">{status}</span></td>
            </tr>
            """
        )
    return "\n".join(rows)


def mobile_fund_cards(funds: list[Fund]) -> str:
    cards = score_cards(funds)
    items = []
    for index, fund in enumerate(funds, 1):
        card = cards[fund.code]
        tier = str(card["tier"])
        score = float(card["score"])
        rank = int(card["rank"])
        status = fund_status(fund.code)
        status_class = fund_status_class(fund.code)
        holding_amount = HOLDING_AMOUNTS.get(fund.code, 0)
        active_amount = AUTO_INVEST_AMOUNTS.get(fund.code, 0)
        paused_amount = PAUSED_AUTO_INVEST_AMOUNTS.get(fund.code, 0)
        if active_amount:
            plan_text = f"{fmt_yuan(active_amount)} / 期"
        elif paused_amount:
            plan_text = f"暂停 {fmt_yuan(paused_amount)} / 期"
        else:
            plan_text = "未设置"
        items.append(
            f"""
            <article class="mobile-fund-card tier-{tier.lower()}-card" data-mobile-card data-status="{html.escape(status)}" data-subscription-status="{html.escape(fund.subscription_status)}" data-tier="{tier}" data-code="{fund.code}" data-score="{score:.1f}">
              <div class="mobile-card-head">
                <div class="mobile-card-title">
                  <strong>{html.escape(fund_display_name(fund))}</strong>
                  <span class="code">{data_text(fund.code)}</span>
                </div>
                <div class="mobile-card-rating">
                  <span class="mobile-rank">#<span class="mobile-rank-number">{data_text(index)}</span></span>
                  <span class="tier-pill {tier_class(tier)}"><strong>{tier}</strong><span>{data_text(f"{score:.1f}")}</span></span>
                </div>
              </div>
              <div class="mobile-card-private">
                <div class="mobile-position-lines">
                  <span><em>持有</em><strong>{fmt_yuan(holding_amount) if holding_amount else data_text("0元")}</strong></span>
                  <span><em>定投</em><strong>{plan_text}</strong></span>
                </div>
                <span class="tag {status_class} mobile-status">{html.escape(status)}</span>
              </div>
              <div class="mobile-metric-grid">
                <div><span>近3年</span><strong>{fmt_percent(fund.three_year)}</strong></div>
                <div><span>近1年</span><strong>{fmt_percent(fund.one_year)}</strong></div>
                <div><span>跟踪误差</span><strong>{fmt_percent(fund.tracking_error)}</strong></div>
                <div><span>管理+托管</span><strong>{fmt_fee(fund.base_annual_fee_rate)}</strong></div>
                <div><span>规模</span><strong>{fmt_size_billion(fund.fund_size_billion)}</strong></div>
                <div><span>买入费率</span><strong>{fmt_buy_rate(fund.buy_rate)}</strong></div>
              </div>
              <div class="mobile-card-foot">
                <span class="tag {subscription_status_class(fund.subscription_status)}">{html.escape(fund.subscription_status)}</span>
                <span>免赎回 满{data_text(fund.free_after_days) if fund.free_after_days is not None else '未知'}天</span>
                <span>代销 {agency_limit_text(fund)}</span>
                <span>直销 {normalize_limit_text(fund.direct_limit)}</span>
              </div>
            </article>
            """
        )
    return "\n".join(line.rstrip() for line in "\n".join(items).splitlines())


def build_html(
    funds: list[Fund],
    tracking_payload: Optional[dict[str, object]] = None,
    tracking_file: Optional[Path] = None,
) -> str:
    generated_at = now_beijing().strftime("%Y-%m-%d %H:%M:%S")
    refresh_schedule_text = " / ".join(AUTO_REFRESH_TIMES_BEIJING)
    rows = main_rows(funds)
    mobile_cards = mobile_fund_cards(funds)
    cards = score_cards(funds)
    if tracking_payload is None:
        tracking_payload = {"schema_version": TRACKING_SCHEMA_VERSION, "records": [default_tracking_record(funds, cards)]}
    tracking_file = tracking_file or (DEFAULT_OUTPUT_DIR / TRACKING_FILENAME)
    tracking_snapshot_table_rows = tracking_snapshot_rows(tracking_payload)
    tracking_year_table_rows = tracking_year_summary_rows(tracking_payload)
    tracking_detail_table_rows = tracking_fund_rows(funds, cards, tracking_payload)
    tracking_visible_count = len(tracking_visible_funds(funds, cards, tracking_payload))
    tracking_asset_chart = tracking_asset_chart_svg(tracking_payload)
    tracking_return_chart = tracking_return_chart_svg(tracking_payload)
    tracking_allocation = tracking_allocation_html(funds, cards, tracking_payload)
    tracking_latest = latest_tracking_record(tracking_payload)
    tracking_count = len(tracking_records(tracking_payload))
    tracking_year_count = tracking_record_year_count(tracking_payload)
    tracking_span = tracking_record_span_label(tracking_payload)
    tracking_latest_date = tracking_latest.get("date") or tracking_latest.get("recorded_at") or "-"
    scoring_rows = scoring_rule_rows()
    funds_by_code = {fund.code: fund for fund in funds}
    holding_rows = holding_record_rows(funds_by_code, cards)
    auto_invest_rows = auto_invest_record_rows(funds_by_code, cards)
    holding_total = sum(HOLDING_AMOUNTS.values())
    active_auto_invest_total = sum(AUTO_INVEST_AMOUNTS.values())
    paused_auto_invest_total = sum(PAUSED_AUTO_INVEST_AMOUNTS.values())
    portfolio_state_json = json.dumps(
        {
            fund.code: {
                "label": fund_display_name(fund),
                "holding": HOLDING_AMOUNTS.get(fund.code, 0),
                "active": AUTO_INVEST_AMOUNTS.get(fund.code, 0),
                "paused": PAUSED_AUTO_INVEST_AMOUNTS.get(fund.code, 0),
            }
            for fund in funds
        },
        ensure_ascii=False,
    )
    sources = []
    for fund in funds:
        source_text = "；".join([*fund.source_notes, fund.direct_limit_source])
        sources.append(
            f'<tr><td data-label="代码">{data_text(fund.code)}</td><td data-label="来源状态">{html.escape(source_text)}</td></tr>'
        )
    source_rows = "\n".join(sources)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>纳指 100 A 类基金池</title>
  <link rel="icon" href="data:,">
  <style>
    :root {{
      color-scheme: light;
      --bg: #f5f4ed;
      --paper: #faf9f5;
      --panel: #faf9f5;
      --panel-subtle: #f1efe6;
      --ink: #141413;
      --ink-soft: #3d3d3a;
      --muted: #6b6a64;
      --line: #e8e6dc;
      --line-strong: #d4d1c5;
      --accent: #1b365d;
      --accent-strong: #173052;
      --good: #2e6648;
      --warn: #8a641d;
      --bad: #8a2f2a;
      --gold: #9a6500;
      --soft-blue: #e4ecf5;
      --soft-green: #e7ede3;
      --soft-orange: #efe8d8;
      --soft-red: #efe1dd;
      --soft-gold: #f0e6c8;
      --shadow: 0 4px 24px rgba(20, 20, 19, 0.05);
      --font-data: "Inter", "Segoe UI", "SF Pro Text", Arial, "Microsoft YaHei UI", sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Charter, Georgia, "Times New Roman", "Source Han Serif SC", "Songti SC", SimSun, serif;
      line-height: 1.45;
      font-weight: 500;
      font-variant-numeric: tabular-nums;
    }}
    button, input {{ font-family: inherit; }}
    .studio-shell {{
      min-height: 100vh;
      display: grid;
      grid-template-columns: minmax(0, 1fr);
    }}
    .studio-main {{ min-width: 0; display: grid; grid-template-rows: minmax(0, 1fr); }}
    .page {{ width: 100%; min-width: 0; margin: 0; padding: 0; }}
    .artifact {{
      background: var(--paper);
      border: 0;
      box-shadow: none;
      min-height: 100vh;
      padding: 34px 36px 28px;
    }}
    .app-header {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 20px;
      align-items: end;
      padding-bottom: 20px;
      border-bottom: 1px solid var(--line-strong);
    }}
    .title-lockup {{ display: grid; gap: 8px; min-width: 0; }}
    h1 {{
      margin: 0;
      color: var(--ink);
      font-size: clamp(31px, 3.1vw, 38px);
      line-height: 1.08;
      letter-spacing: 0;
      font-weight: 500;
    }}
    .title-number {{
      font-family: var(--font-data);
      font-variant-numeric: tabular-nums;
      font-weight: 550;
      letter-spacing: 0;
    }}
    .subtitle {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px;
      margin: 0;
      color: var(--muted);
      font-size: 12px;
    }}
    .subtitle-chip {{
      align-items: center;
      background: var(--panel-subtle);
      border: 1px solid var(--line);
      border-radius: 3px;
      color: var(--ink-soft);
      display: inline-flex;
      font-size: 12px;
      font-weight: 500;
      min-height: 24px;
      padding: 3px 7px;
      white-space: nowrap;
    }}
    .subtitle-meta {{
      min-width: min(100%, 420px);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .data-text,
    .numeric {{
      font-family: var(--font-data);
      font-variant-numeric: tabular-nums;
      letter-spacing: 0;
    }}
    .subtitle,
    .header-actions,
    .header-control-bar,
    .table-toolbar,
    table,
    .notes,
    .visible-count,
    .tabs {{
      font-family: var(--font-data);
      font-variant-numeric: tabular-nums;
      letter-spacing: 0;
    }}
    .header-actions {{
      align-items: flex-end;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      justify-items: end;
      justify-content: flex-end;
      max-width: 620px;
    }}
    .header-control-bar {{
      align-items: center;
      background: #f1efe6;
      border: 1px solid var(--line);
      border-radius: 4px;
      display: inline-flex;
      flex-wrap: wrap;
      gap: 6px;
      justify-content: flex-end;
      padding: 4px;
    }}
    .section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 0;
      box-shadow: var(--shadow);
      margin-top: 12px;
      overflow: hidden;
    }}
    .section-title {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      justify-content: space-between;
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      background: var(--paper);
    }}
    .title-copy {{ display: grid; gap: 3px; }}
    h2 {{ margin: 0; font-size: 20px; line-height: 1.2; font-weight: 500; }}
    .hint {{ color: var(--muted); font-size: 13px; }}
    .title-metric {{
      color: var(--ink-soft);
      font-family: var(--font-data);
      font-size: 13px;
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }}
    .title-metric strong {{
      color: var(--ink);
      font-size: 15px;
      font-weight: 600;
    }}
    .table-toolbar {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 12px 16px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }}
    .visible-count {{ color: var(--muted); font-size: 13px; white-space: nowrap; }}
    .table-controls {{ display: flex; flex: 1 1 auto; flex-wrap: wrap; align-items: center; justify-content: flex-start; gap: 9px; }}
    .filter-control {{ display: inline-flex; align-items: center; gap: 8px; }}
    .filter-label {{ color: var(--muted); font-size: 13px; white-space: nowrap; }}
    .select-menu {{ position: relative; min-width: 150px; }}
    .select-trigger {{
      width: 100%;
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 4px;
      background: var(--panel);
      color: var(--ink);
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 7px 10px 7px 12px;
      font: inherit;
      font-size: 13px;
      font-weight: 500;
      box-shadow: 0 1px 2px rgba(20, 20, 19, 0.04);
    }}
    .select-trigger::after {{
      content: "";
      width: 7px;
      height: 7px;
      border-right: 2px solid var(--muted);
      border-bottom: 2px solid var(--muted);
      transform: rotate(45deg) translateY(-2px);
    }}
    .select-trigger[aria-expanded="true"]::after {{
      transform: rotate(225deg) translateY(-1px);
    }}
    .select-list {{
      position: absolute;
      right: 0;
      top: calc(100% + 6px);
      z-index: 20;
      width: 100%;
      min-width: 144px;
      margin: 0;
      padding: 5px;
      list-style: none;
      border: 1px solid var(--line);
      border-radius: 4px;
      background: var(--panel);
      box-shadow: 0 4px 24px rgba(20, 20, 19, 0.12);
    }}
    .select-list[hidden] {{ display: none; }}
    .select-option {{
      border-radius: 3px;
      cursor: pointer;
      font-size: 13px;
      font-weight: 500;
      padding: 8px 9px;
      color: var(--ink-soft);
    }}
    .select-option:hover, .select-option[aria-selected="true"] {{
      background: var(--soft-blue);
      color: var(--accent);
    }}
    .ghost-button {{
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 4px;
      background: var(--panel);
      color: var(--accent);
      cursor: pointer;
      font: inherit;
      font-size: 13px;
      font-weight: 500;
      padding: 7px 11px;
    }}
    .ghost-button:hover {{ border-color: var(--line-strong); background: var(--soft-blue); }}
    .column-menu {{
      position: relative;
    }}
    .column-panel {{
      position: absolute;
      right: 0;
      top: calc(100% + 6px);
      z-index: 30;
      width: 286px;
      border: 1px solid var(--line);
      border-radius: 4px;
      background: var(--panel);
      box-shadow: 0 4px 24px rgba(20, 20, 19, 0.12);
      padding: 10px;
    }}
    .column-panel[hidden] {{ display: none; }}
    .column-panel-head {{
      align-items: center;
      display: flex;
      justify-content: space-between;
      gap: 10px;
      padding: 2px 2px 9px;
      border-bottom: 1px solid var(--line);
    }}
    .column-panel-title {{
      color: var(--ink);
      font-size: 13px;
      font-weight: 600;
    }}
    .column-reset {{
      border: 0;
      background: transparent;
      color: var(--accent);
      cursor: pointer;
      font: inherit;
      font-size: 12px;
      padding: 2px 0;
    }}
    .column-options {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 6px;
      padding-top: 9px;
    }}
    .column-option {{
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 4px;
      color: var(--ink-soft);
      cursor: pointer;
      display: flex;
      gap: 7px;
      min-height: 34px;
      padding: 6px 8px;
      font-size: 12px;
      user-select: none;
    }}
    .column-option:hover {{ background: var(--soft-blue); color: var(--accent); }}
    .column-option.locked {{ cursor: default; color: var(--muted); background: #f7f5ee; }}
    .column-option input {{
      accent-color: var(--accent);
      height: 14px;
      margin: 0;
      width: 14px;
    }}
    .column-option input:disabled {{ opacity: 0.55; }}
    .is-column-hidden {{ display: none !important; }}
    .table-wrap {{
      background: var(--panel);
      overflow: auto;
      max-height: calc(100vh - 205px);
      min-height: 360px;
      position: relative;
    }}
    .mobile-fund-list {{
      display: none;
    }}
    table {{ width: max-content; border-collapse: separate; border-spacing: 0; min-width: 1970px; font-size: 13px; }}
    #main-table {{
      border-collapse: separate;
      isolation: isolate;
      table-layout: fixed;
      width: 2168px;
      min-width: 2168px;
    }}
    col.rank-col {{ width: 48px; }}
    col.tier-col {{ width: 98px; }}
    col.fund-col {{ width: 300px; }}
    col.position-col {{ width: 124px; }}
    col.status-col {{ width: 86px; }}
    col.status-detail-col {{ width: 90px; }}
    col.size-col {{ width: 92px; }}
    col.limit-col {{ width: 104px; }}
    col.fee-col {{ width: 100px; }}
    col.tracking-col {{ width: 160px; }}
    col.detail-col {{ width: 170px; }}
    col.rules-col {{ width: 210px; }}
    col.return-col {{ width: 94px; }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 9px 11px;
      text-align: left;
      vertical-align: middle;
    }}
    #main-table th,
    #main-table td {{
      text-align: center;
    }}
    #main-table th:nth-child(3),
    #main-table td:nth-child(3),
    #main-table th:nth-child(4),
    #main-table td:nth-child(4),
    #main-table th:nth-child(7),
    #main-table td:nth-child(7),
    #main-table th:nth-child(15),
    #main-table td:nth-child(15),
    #main-table th:nth-child(16),
    #main-table td:nth-child(16) {{
      text-align: left;
    }}
    #main-table th:nth-child(-n+2), #main-table td:nth-child(-n+2) {{
      padding-left: 8px;
      padding-right: 8px;
      text-align: center;
    }}
    #main-table th:nth-child(1), #main-table td:nth-child(1) {{
      padding-left: 6px;
      padding-right: 6px;
      text-align: center;
    }}
    #main-table th:nth-child(2), #main-table td:nth-child(2) {{
      padding-left: 6px;
      padding-right: 6px;
      text-align: center;
    }}
    th {{
      position: sticky;
      top: 0;
      z-index: 6;
      background: #f1efe6;
      color: var(--ink-soft);
      font-weight: 500;
      white-space: nowrap;
      border-bottom: 1px solid var(--line-strong);
    }}
    th.sortable {{ padding: 0; }}
    .sort-button {{
      width: 100%;
      min-height: 43px;
      border: 0;
      background: transparent;
      color: inherit;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      padding: 10px 12px;
      font: inherit;
      font-size: 12px;
      font-weight: 500;
      text-align: center;
      white-space: nowrap;
    }}
    #main-table th:nth-child(3) .sort-button,
    #main-table th:nth-child(7) .sort-button,
    #main-table th:nth-child(15) .sort-button,
    #main-table th:nth-child(16) .sort-button {{
      justify-content: flex-start;
      text-align: left;
    }}
    .sort-button:hover, .sort-button:focus-visible {{ background: #e8e6dc; outline: none; }}
    .sort-indicator {{ width: 12px; color: var(--muted); font-size: 12px; }}
    tbody tr td {{ background: var(--panel); }}
    tbody tr:nth-child(even) td {{ background: #f7f5ee; }}
    tbody tr:hover td {{ background: #eef2f7; }}
    tbody tr[hidden] {{ display: none; }}
    #main-table th:nth-child(1), #main-table td:nth-child(1),
    #main-table th:nth-child(2), #main-table td:nth-child(2),
    #main-table th:nth-child(3), #main-table td:nth-child(3),
    #main-table th:nth-child(4), #main-table td:nth-child(4) {{
      position: sticky;
      background: var(--panel);
      background-clip: border-box;
      isolation: isolate;
      z-index: 16;
    }}
    #main-table tbody tr:nth-child(even) td:nth-child(-n+4) {{ background: #f7f5ee; }}
    #main-table tbody tr:nth-child(odd) td:nth-child(-n+4) {{ background: var(--panel); }}
    #main-table tbody tr:hover td:nth-child(-n+4) {{ background: #eef2f7; }}
    #main-table th:nth-child(1), #main-table td:nth-child(1) {{ left: 0; }}
    #main-table th:nth-child(2), #main-table td:nth-child(2) {{ left: 48px; }}
    #main-table th:nth-child(3), #main-table td:nth-child(3) {{ left: 146px; }}
    #main-table th:nth-child(4), #main-table td:nth-child(4) {{
      left: 446px;
      box-shadow: 1px 0 0 var(--line-strong);
    }}
    #main-table th:nth-child(-n+4) {{
      background: #f1efe6;
      background-clip: border-box;
      z-index: 26;
    }}
    #main-table td:nth-child(-n+4) {{ z-index: 16; }}
    .tier-s-row td:first-child {{ box-shadow: inset 4px 0 var(--accent); }}
    .tier-a-row td:first-child {{ box-shadow: inset 4px 0 var(--good); }}
    .tier-b-row td:first-child {{ box-shadow: inset 4px 0 var(--accent); }}
    .tier-c-row td:first-child {{ box-shadow: inset 4px 0 var(--warn); }}
    .tier-d-row td:first-child {{ box-shadow: inset 4px 0 var(--bad); }}
    .num {{
      text-align: right;
      white-space: nowrap;
      font-family: var(--font-data);
      font-variant-numeric: tabular-nums;
      letter-spacing: 0;
    }}
    #main-table .num {{
      text-align: center;
    }}
    td[data-sort-value] {{
      font-variant-numeric: tabular-nums;
    }}
    #main-table td:nth-child(5),
    #main-table td:nth-child(6),
    #main-table td:nth-child(8),
    #main-table td:nth-child(9),
    #main-table td:nth-child(10),
    #main-table td:nth-child(11),
    #main-table td:nth-child(13),
    #main-table td:nth-child(14),
    #main-table td:nth-child(17),
    #main-table td:nth-child(18),
    .position-line strong,
    .tier-pill,
    .tag,
    .rule-line strong,
    .tracking-detail strong {{
      font-family: var(--font-data);
      font-variant-numeric: tabular-nums;
      letter-spacing: 0;
    }}
    .fund-cell {{ min-width: 280px; font-weight: 500; }}
    .fund {{
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 3px;
      align-items: center;
    }}
    .fund-name {{
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .code {{ font-family: ui-monospace, Consolas, "SFMono-Regular", monospace; color: var(--muted); white-space: nowrap; font-size: 12px; }}
    .position-plan {{
      display: grid;
      gap: 5px;
      min-width: 108px;
    }}
    .position-line {{
      align-items: baseline;
      display: flex;
      gap: 4px;
      justify-content: flex-start;
      white-space: nowrap;
    }}
    .position-line em {{
      color: var(--muted);
      font-size: 11px;
      font-style: normal;
    }}
    .position-line strong {{
      color: var(--ink);
      font-size: 12px;
      font-weight: 500;
      font-family: var(--font-data);
      font-variant-numeric: tabular-nums;
    }}
    .position-line.paused-line strong {{ color: var(--bad); }}
    .position-line.muted-line strong {{ color: var(--muted); }}
    .tag {{
      display: inline-flex;
      align-items: center;
      border-radius: 4px;
      padding: 2px 8px;
      font-size: 12px;
      font-weight: 500;
      white-space: nowrap;
    }}
    .tag.good, .tag.owned {{ color: var(--good); background: var(--soft-green); }}
    .tag.warn {{ color: var(--warn); background: var(--soft-orange); }}
    .tag.bad, .tag.paused {{ color: var(--bad); background: var(--soft-red); }}
    .tag.info, .tag.watch {{ color: var(--accent); background: var(--soft-blue); }}
    .tier-pill {{
      align-items: center;
      border-radius: 4px;
      display: inline-flex;
      gap: 6px;
      justify-content: center;
      min-width: 70px;
      padding: 4px 7px;
      font-size: 12px;
      font-weight: 500;
    }}
    .tier-pill strong {{
      align-items: center;
      border-radius: 3px;
      display: inline-flex;
      justify-content: center;
      min-width: 22px;
      min-height: 22px;
      color: var(--paper);
      font-size: 13px;
    }}
    .tier-s {{ color: var(--gold); background: var(--soft-gold); }}
    .tier-s strong {{ background: var(--accent); }}
    .tier-a {{ color: var(--good); background: var(--soft-green); }}
    .tier-a strong {{ background: var(--good); }}
    .tier-b {{ color: var(--accent); background: var(--soft-blue); }}
    .tier-b strong {{ background: var(--accent); }}
    .tier-c {{ color: var(--warn); background: var(--soft-orange); }}
    .tier-c strong {{ background: var(--warn); }}
    .tier-d {{ color: var(--bad); background: var(--soft-red); }}
    .tier-d strong {{ background: var(--bad); }}
    .fee-detail, .tracking-detail, .sell-rules {{ display: grid; gap: 5px; min-width: 0; width: 100%; }}
    .fee-detail span {{ color: var(--muted); font-size: 12px; line-height: 1.45; overflow-wrap: anywhere; }}
    .tracking-detail strong {{ color: var(--accent); font-size: 13px; font-weight: 500; white-space: nowrap; }}
    .tracking-detail span {{ color: var(--muted); font-size: 12px; line-height: 1.45; overflow-wrap: anywhere; }}
    .muted-cell {{ color: var(--muted); font-size: 12px; white-space: nowrap; }}
    .rule-line {{
      display: grid;
      grid-template-columns: minmax(88px, 1fr) auto;
      align-items: center;
      gap: 10px;
      border: 1px solid var(--line);
      border-radius: 3px;
      padding: 4px 6px;
      background: #f1efe6;
      white-space: nowrap;
    }}
    .rule-line span {{ color: var(--muted); font-size: 12px; }}
    .rule-line strong {{ font-size: 12px; }}
    .notes {{
      padding: 13px 16px 16px;
      color: var(--muted);
      font-size: 12px;
      background: #f7f5ee;
      border-top: 1px solid var(--line);
    }}
    .notes p {{ margin: 6px 0; }}
    .scoring-wrap {{ max-height: none; min-height: 0; }}
    .scoring-table {{
      min-width: 0;
      table-layout: fixed;
      width: 100%;
    }}
    .scoring-table th:nth-child(1) {{ width: 12%; }}
    .scoring-table th:nth-child(2) {{ width: 8%; }}
    .scoring-table th:nth-child(3) {{ width: 10%; }}
    .scoring-table th:nth-child(4) {{ width: 24%; }}
    .scoring-table th:nth-child(5) {{ width: 46%; }}
    .scoring-table th,
    .scoring-table td {{
      overflow-wrap: anywhere;
      white-space: normal;
    }}
    .small-table {{ min-width: 760px; }}
    .tabs {{
      display: inline-flex;
      gap: 3px;
      padding: 0;
      border: 0;
      border-radius: 0;
      background: transparent;
      margin: 0;
    }}
    .tab-button {{
      border: 0;
      border-radius: 3px;
      background: transparent;
      color: var(--ink-soft);
      cursor: pointer;
      font: inherit;
      font-size: 13px;
      font-weight: 500;
      min-height: 36px;
      padding: 8px 14px;
      white-space: nowrap;
    }}
    .tab-button[aria-selected="true"] {{
      background: var(--panel);
      color: var(--ink);
      box-shadow: 0 2px 10px rgba(20, 20, 19, 0.05);
    }}
    .tab-button:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
    .tab-panel[hidden] {{ display: none; }}
    .rank-good {{ color: var(--good); font-weight: 500; }}
    .rank-bad {{ color: var(--bad); font-weight: 500; }}
    .source-panel .section-title {{ background: var(--panel); }}
    .source-table {{
      min-width: 0;
      table-layout: fixed;
      width: 100%;
    }}
    .source-table th:first-child,
    .source-table td:first-child {{
      width: 76px;
      white-space: nowrap;
    }}
    .source-table th:nth-child(2),
    .source-table td:nth-child(2) {{
      line-height: 1.55;
      overflow-wrap: anywhere;
      white-space: normal;
    }}
    .portfolio-grid {{
      display: grid;
      grid-template-columns: minmax(390px, 0.82fr) minmax(520px, 1.18fr);
      align-items: start;
      gap: 0;
      border: 1px solid var(--line);
      background: var(--panel);
      overflow: hidden;
    }}
    .portfolio-block {{
      min-width: 0;
      border: 0;
      background: var(--panel);
      height: fit-content;
    }}
    .portfolio-block + .portfolio-block {{
      border-left: 1px solid var(--line);
    }}
    .portfolio-block .section-title {{
      background: #f7f5ee;
      min-height: 56px;
      padding-top: 13px;
      padding-bottom: 13px;
    }}
    .compact-table-wrap {{
      max-height: none;
      min-height: 0;
      height: fit-content;
    }}
    .portfolio-table {{
      table-layout: fixed;
      width: 100%;
      min-width: 0;
    }}
    .portfolio-table col.record-col {{ width: 8%; }}
    .portfolio-table col.rating-col {{ width: 18%; }}
    .holding-table col.holding-fund-col {{ width: 29%; }}
    .holding-table col.holding-amount-col {{ width: 22%; }}
    .holding-table col.holding-status-col {{ width: 23%; }}
    .auto-plan-table col.record-col {{ width: 6%; }}
    .auto-plan-table col.auto-fund-col {{ width: 24%; }}
    .auto-plan-table col.auto-status-col {{ width: 18%; }}
    .auto-plan-table col.auto-amount-col {{ width: 20%; }}
    .auto-plan-table col.auto-holding-col {{ width: 17%; }}
    .portfolio-table th,
    .portfolio-table td {{
      padding-left: clamp(8px, 0.85vw, 12px);
      padding-right: clamp(8px, 0.85vw, 12px);
    }}
    .portfolio-table th,
    .portfolio-table td {{
      padding-top: 10px;
      padding-bottom: 10px;
    }}
    .portfolio-table th,
    .portfolio-table td {{ overflow-wrap: anywhere; }}
    .portfolio-table .num,
    .portfolio-table .tag {{ white-space: nowrap; }}
    .portfolio-tier {{
      min-width: 64px;
      padding-left: 5px;
      padding-right: 5px;
    }}
    .portfolio-tier strong {{
      min-width: 20px;
      min-height: 20px;
      font-size: 12px;
    }}
    .editable-amount,
    .editable-status {{
      cursor: pointer;
      position: relative;
      transition: background-color 120ms ease, box-shadow 120ms ease, color 120ms ease;
    }}
    .editable-amount:hover,
    .editable-amount:focus-visible,
    .editable-status:hover,
    .editable-status:focus-visible {{
      background: rgba(228, 236, 245, 0.52);
      box-shadow: inset 0 -1px 0 var(--accent);
      outline: none;
    }}
    .portfolio-editor {{
      position: fixed;
      z-index: 80;
      width: min(270px, calc(100vw - 24px));
      border: 1px solid var(--line-strong);
      background: rgba(250, 249, 245, 0.98);
      box-shadow: 0 18px 40px rgba(20, 20, 19, 0.16);
      padding: 6px;
      backdrop-filter: blur(12px);
    }}
    .portfolio-editor[hidden] {{ display: none; }}
    .editor-panel {{
      display: grid;
      gap: 8px;
    }}
    .editor-row {{
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .editor-input {{
      width: 100%;
      min-width: 0;
      height: 38px;
      border: 1px solid var(--line-strong);
      border-radius: 3px;
      background: #fffef9;
      color: var(--ink);
      font-family: var(--font-data);
      font-size: 16px;
      font-weight: 600;
      font-variant-numeric: tabular-nums;
      padding: 7px 9px;
      outline: none;
    }}
    .editor-input:focus {{
      border-color: var(--accent);
      box-shadow: 0 0 0 2px rgba(27, 54, 93, 0.12);
    }}
    .editor-suffix {{
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }}
    .editor-action {{
      border: 1px solid var(--line);
      border-radius: 3px;
      background: var(--panel);
      color: var(--ink-soft);
      cursor: pointer;
      font: inherit;
      font-family: inherit;
      font-size: 12px;
      font-weight: 500;
      min-height: 30px;
      padding: 5px 9px;
      white-space: nowrap;
    }}
    .editor-action.primary {{
      background: var(--accent);
      border-color: var(--accent);
      color: #fffdf8;
    }}
    .editor-action:hover {{
      border-color: var(--accent);
      color: var(--accent);
    }}
    .editor-action.primary:hover {{
      background: var(--accent-strong);
      color: #fffdf8;
    }}
    .editor-options {{
      display: grid;
      gap: 4px;
    }}
    .editor-option {{
      width: 100%;
      border: 1px solid transparent;
      border-radius: 3px;
      background: transparent;
      color: var(--ink-soft);
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      font: inherit;
      font-size: 13px;
      min-height: 36px;
      padding: 7px 9px;
      text-align: left;
    }}
    .editor-option:hover,
    .editor-option:focus-visible {{
      background: var(--soft-blue);
      border-color: rgba(27, 54, 93, 0.16);
      color: var(--accent);
      outline: none;
    }}
    .editor-option[aria-selected="true"] {{
      background: #f1efe6;
      border-color: var(--line-strong);
      color: var(--ink);
    }}
    .editor-option[aria-selected="true"]::after {{
      content: "";
      width: 7px;
      height: 12px;
      border-right: 2px solid var(--accent);
      border-bottom: 2px solid var(--accent);
      transform: rotate(45deg);
    }}
    .record-index {{
      color: var(--muted);
      width: 32px;
      min-width: 32px;
    }}
    .portfolio-table th:first-child,
    .portfolio-table td:first-child {{
      padding-left: 10px;
      padding-right: 8px;
    }}
    .tracking-head {{
      align-items: flex-end;
      background: var(--panel);
      gap: 12px;
    }}
    .tracking-metrics {{
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 8px;
      font-family: var(--font-data);
    }}
    .tracking-metric {{
      align-items: baseline;
      background: #f7f5ee;
      border: 1px solid var(--line);
      border-radius: 4px;
      color: var(--muted);
      display: inline-flex;
      gap: 6px;
      min-height: 30px;
      padding: 5px 8px;
      white-space: nowrap;
      font-size: 12px;
    }}
    .tracking-metric strong {{
      color: var(--ink);
      font-size: 14px;
      font-weight: 600;
    }}
    .tracking-subtabs {{
      align-items: center;
      background: #f7f5ee;
      border-top: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      padding: 8px 12px;
    }}
    .tracking-subtab {{
      border: 1px solid transparent;
      border-radius: 3px;
      background: transparent;
      color: var(--ink-soft);
      cursor: pointer;
      font-family: var(--font-data);
      font-size: 13px;
      font-weight: 500;
      min-height: 32px;
      padding: 6px 12px;
      white-space: nowrap;
    }}
    .tracking-subtab[aria-selected="true"] {{
      background: var(--panel);
      border-color: var(--line);
      color: var(--ink);
      box-shadow: 0 1px 8px rgba(20, 20, 19, 0.05);
    }}
    .tracking-subtab:focus-visible {{
      outline: 2px solid var(--accent);
      outline-offset: 2px;
    }}
    .tracking-subpanel[hidden] {{ display: none; }}
    .tracking-overview-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(150px, 1fr));
      background: var(--panel);
    }}
    .tracking-overview-card {{
      border-bottom: 1px solid var(--line);
      min-width: 0;
      padding: 13px 15px;
    }}
    .tracking-overview-card + .tracking-overview-card {{
      border-left: 1px solid var(--line);
    }}
    .tracking-overview-card > span {{
      color: var(--muted);
      display: block;
      font-family: var(--font-data);
      font-size: 12px;
      margin-bottom: 5px;
      white-space: nowrap;
    }}
    .tracking-overview-card strong .data-text {{
      display: inline;
    }}
    .tracking-overview-card strong {{
      color: var(--ink);
      display: block;
      font-family: var(--font-data);
      font-size: 19px;
      font-variant-numeric: tabular-nums;
      font-weight: 600;
      line-height: 1.2;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .tracking-grid {{
      display: grid;
      grid-template-columns: minmax(330px, 0.76fr) minmax(620px, 1.24fr);
      align-items: start;
      background: var(--panel);
    }}
    .tracking-chart-grid {{
      display: grid;
      grid-template-columns: minmax(420px, 1.15fr) minmax(320px, 0.85fr);
      background: var(--panel);
    }}
    .tracking-single-panel {{
      background: var(--panel);
      min-width: 0;
    }}
    .tracking-single-panel .tracking-chart-card,
    .tracking-single-panel .tracking-allocation-card {{
      border-left: 0;
    }}
    .tracking-chart-stack {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      min-width: 0;
    }}
    .tracking-overview-panel .tracking-chart-stack {{
      border-top: 1px solid var(--line);
    }}
    .tracking-chart-card,
    .tracking-allocation-card {{
      min-width: 0;
      background: var(--panel);
    }}
    .tracking-chart-card + .tracking-chart-card,
    .tracking-allocation-card {{
      border-left: 1px solid var(--line);
    }}
    .tracking-chart-card .section-title,
    .tracking-allocation-card .section-title {{
      background: #f7f5ee;
      min-height: 52px;
      padding-top: 12px;
      padding-bottom: 12px;
    }}
    .chart-frame {{
      padding: 12px 14px 14px;
      min-height: 236px;
    }}
    .tracking-chart-svg {{
      display: block;
      width: 100%;
      height: auto;
      min-height: 210px;
    }}
    .chart-bg {{ fill: #faf9f5; }}
    .chart-grid {{
      stroke: var(--line);
      stroke-width: 1;
    }}
    .chart-axis {{
      fill: var(--muted);
      font-family: var(--font-data);
      font-size: 11px;
    }}
    .chart-empty {{
      fill: var(--muted);
      font-family: var(--font-data);
      font-size: 13px;
    }}
    .chart-series {{
      fill: none;
      stroke-linecap: round;
      stroke-linejoin: round;
      stroke-width: 2.3;
    }}
    .chart-series-1 {{ stroke: var(--accent); }}
    .chart-series-2 {{ stroke: var(--good); }}
    .chart-point {{
      stroke: var(--panel);
      stroke-width: 2;
    }}
    .chart-point-1 {{ fill: var(--accent); }}
    .chart-point-2 {{ fill: var(--good); }}
    .chart-legend {{
      align-items: center;
      display: flex;
      gap: 12px;
      height: 22px;
      font-family: var(--font-data);
      font-size: 11px;
      color: var(--muted);
    }}
    .chart-legend-item {{
      align-items: center;
      display: inline-flex;
      gap: 5px;
      white-space: nowrap;
    }}
    .legend-dot {{
      border-radius: 99px;
      display: inline-block;
      height: 7px;
      width: 7px;
    }}
    .legend-dot-1 {{ background: var(--accent); }}
    .legend-dot-2 {{ background: var(--good); }}
    .allocation-list {{
      display: grid;
      gap: 10px;
      padding: 14px;
    }}
    .allocation-row {{
      display: grid;
      gap: 6px;
      min-width: 0;
    }}
    .allocation-head {{
      align-items: center;
      display: flex;
      justify-content: space-between;
      gap: 12px;
      font-family: var(--font-data);
      font-size: 12px;
      min-width: 0;
    }}
    .allocation-head > span {{
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .allocation-head strong {{
      color: var(--ink);
      font-weight: 600;
      white-space: nowrap;
    }}
    .allocation-track {{
      background: #ebe8dc;
      border-radius: 99px;
      height: 7px;
      overflow: hidden;
    }}
    .allocation-track span {{
      display: block;
      height: 100%;
      min-width: 3px;
    }}
    .allocation-track .tier-s {{ background: var(--accent); }}
    .allocation-track .tier-a {{ background: var(--good); }}
    .allocation-track .tier-b {{ background: #52759f; }}
    .allocation-track .tier-c {{ background: var(--warn); }}
    .allocation-track .tier-d {{ background: var(--bad); }}
    .allocation-empty {{
      color: var(--muted);
      font-family: var(--font-data);
      font-size: 13px;
      padding: 14px;
    }}
    .tracking-block {{
      min-width: 0;
      background: var(--panel);
    }}
    .tracking-block + .tracking-block {{
      border-left: 1px solid var(--line);
    }}
    .tracking-block .section-title {{
      background: #f7f5ee;
      min-height: 52px;
      padding-top: 12px;
      padding-bottom: 12px;
    }}
    .tracking-table {{
      table-layout: fixed;
      width: 100%;
      min-width: 0;
    }}
    .tracking-table th,
    .tracking-table td {{
      padding: 10px 9px;
      overflow-wrap: anywhere;
    }}
    .tracking-table .num,
    .tracking-table .data-text,
    .tracking-table .muted-cell {{
      white-space: nowrap;
    }}
    .tracking-history-table col.record-col {{ width: 9%; }}
    .tracking-history-table col.date-col {{ width: 23%; }}
    .tracking-history-table col.amount-col {{ width: 17%; }}
    .tracking-year-table col.year-col {{ width: 10%; }}
    .tracking-year-table col.count-col {{ width: 9%; }}
    .tracking-year-table col.date-col {{ width: 13%; }}
    .tracking-year-table col.amount-col {{ width: 13%; }}
    .tracking-fund-table col.record-col {{ width: 7%; }}
    .tracking-fund-table col.fund-col-small {{ width: 18%; }}
    .tracking-fund-table col.rating-col {{ width: 13%; }}
    .tracking-fund-table col.amount-col {{ width: 13%; }}
    .tracking-fund-table col.plan-col {{ width: 15%; }}
    .holding-table th:nth-child(1),
    .holding-table td:nth-child(1),
    .holding-table th:nth-child(3),
    .holding-table td:nth-child(3),
    .holding-table th:nth-child(4),
    .holding-table td:nth-child(4),
    .holding-table th:nth-child(5),
    .holding-table td:nth-child(5),
    .auto-plan-table th:nth-child(1),
    .auto-plan-table td:nth-child(1),
    .auto-plan-table th:nth-child(3),
    .auto-plan-table td:nth-child(3),
    .auto-plan-table th:nth-child(4),
    .auto-plan-table td:nth-child(4),
    .auto-plan-table th:nth-child(5),
    .auto-plan-table td:nth-child(5),
    .auto-plan-table th:nth-child(6),
    .auto-plan-table td:nth-child(6) {{
      text-align: center;
    }}
    .holding-table th:nth-child(2),
    .holding-table td:nth-child(2),
    .auto-plan-table th:nth-child(2),
    .auto-plan-table td:nth-child(2) {{
      white-space: nowrap;
    }}
    @media (max-width: 1100px) {{
      .studio-shell {{ grid-template-columns: 1fr; }}
      .page {{ padding: 0; }}
      .artifact {{ min-height: 100vh; padding: 22px 18px; }}
    }}
    @media (max-width: 900px) {{
      .app-header {{ grid-template-columns: 1fr; }}
      .header-actions {{ align-items: flex-start; justify-content: flex-start; justify-items: start; max-width: none; width: 100%; }}
      .header-control-bar {{ justify-content: flex-start; width: 100%; }}
      h1 {{ font-size: 30px; }}
      .portfolio-grid {{ grid-template-columns: 1fr; }}
      .tracking-overview-grid {{ grid-template-columns: repeat(2, minmax(150px, 1fr)); }}
      .tracking-overview-card:nth-child(odd) {{ border-left: 0; }}
      .tracking-overview-card:nth-child(n+3) {{ border-top: 0; }}
      .tracking-chart-grid {{ grid-template-columns: 1fr; }}
      .tracking-chart-stack {{ grid-template-columns: 1fr; }}
      .tracking-grid {{ grid-template-columns: 1fr; }}
      .portfolio-block + .portfolio-block {{
        border-left: 0;
        border-top: 1px solid var(--line);
      }}
      .tracking-chart-card + .tracking-chart-card,
      .tracking-allocation-card {{
        border-left: 0;
        border-top: 1px solid var(--line);
      }}
      .tracking-block + .tracking-block {{
        border-left: 0;
        border-top: 1px solid var(--line);
      }}
      .tracking-metrics {{ justify-content: flex-start; }}
      .section-title {{ align-items: stretch; }}
      .table-controls {{ width: 100%; justify-content: flex-start; }}
    }}
    @media (max-width: 900px) {{
      html {{ background: var(--panel); }}
      body {{ background: var(--panel); }}
      .artifact {{ padding: 14px 10px 18px; }}
      .app-header,
      .title-lockup,
      .subtitle,
      .header-actions,
      .header-control-bar {{
        min-width: 0;
        max-width: 100%;
      }}
      .app-header {{
        gap: 12px;
        padding-bottom: 12px;
      }}
      h1 {{
        font-size: 25px;
        line-height: 1.15;
        max-width: 100%;
        overflow-wrap: anywhere;
      }}
      .title-number {{
        font-family: inherit;
        font-weight: 600;
      }}
      .subtitle {{
        align-items: flex-start;
        gap: 5px;
      }}
      .subtitle-meta {{
        flex: 1 1 100%;
        min-width: 0;
        width: 100%;
        white-space: normal;
        overflow: visible;
        text-overflow: clip;
        line-height: 1.45;
      }}
      .header-actions {{
        overflow: hidden;
        width: 100%;
      }}
      .header-control-bar {{
        overflow: visible;
        width: 100%;
        justify-content: flex-start;
        scrollbar-width: none;
      }}
      .header-control-bar::-webkit-scrollbar {{ display: none; }}
      .tabs {{
        display: inline-flex;
        flex-wrap: wrap;
        flex: 1 1 auto;
        min-width: 0;
        width: 100%;
      }}
      .tab-button {{
        flex: 1 1 auto;
        min-height: 34px;
        padding: 7px 8px;
        white-space: nowrap;
      }}
      .section {{
        margin-top: 10px;
      }}
      .table-toolbar {{
        align-items: stretch;
        gap: 9px;
        padding: 10px;
      }}
      .table-controls {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 8px;
        width: 100%;
      }}
      .filter-control {{
        align-items: stretch;
        display: grid;
        gap: 4px;
      }}
      .filter-label {{
        font-size: 12px;
      }}
      .select-menu {{
        min-width: 0;
        width: 100%;
      }}
      .select-trigger,
      .ghost-button {{
        min-height: 34px;
        padding: 7px 9px;
      }}
      #column-menu {{
        display: none;
      }}
      #reset-filters {{
        width: 100%;
      }}
      .visible-count {{
        order: 2;
        width: 100%;
        text-align: left;
      }}
      #panel-main > .table-wrap {{
        display: none;
      }}
      .mobile-fund-list {{
        background: var(--panel);
        display: grid;
        gap: 8px;
        padding: 8px;
      }}
      .mobile-fund-card {{
        border: 1px solid var(--line);
        background: var(--panel);
        display: grid;
        gap: 9px;
        padding: 11px;
      }}
      .mobile-fund-card[hidden] {{
        display: none;
      }}
      .tier-s-card {{ border-left: 4px solid var(--accent); }}
      .tier-a-card {{ border-left: 4px solid var(--good); }}
      .tier-b-card {{ border-left: 4px solid var(--accent); }}
      .tier-c-card {{ border-left: 4px solid var(--warn); }}
      .tier-d-card {{ border-left: 4px solid var(--bad); }}
      .mobile-card-head {{
        display: grid;
        gap: 7px;
      }}
      .mobile-card-title {{
        align-items: center;
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        min-width: 0;
      }}
      .mobile-card-title strong {{
        color: var(--ink);
        font-size: 15px;
        font-weight: 600;
      }}
      .mobile-card-rating {{
        align-items: center;
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        justify-content: flex-start;
        min-width: 0;
      }}
      .mobile-rank {{
        color: var(--muted);
        font-family: var(--font-data);
        font-size: 12px;
      }}
      .mobile-card-rating .tier-pill {{
        flex: 0 0 auto;
      }}
      .mobile-card-private {{
        border-top: 1px solid var(--line);
        display: grid;
        gap: 7px;
        padding-top: 9px;
      }}
      .mobile-position-lines {{
        display: flex;
        flex-wrap: wrap;
        gap: 7px 12px;
      }}
      .mobile-position-lines span {{
        align-items: baseline;
        display: inline-flex;
        gap: 4px;
        white-space: nowrap;
      }}
      .mobile-position-lines em {{
        color: var(--muted);
        font-style: normal;
        font-size: 12px;
      }}
      .mobile-position-lines strong {{
        color: var(--ink);
        font-family: var(--font-data);
        font-size: 13px;
        font-weight: 600;
      }}
      .mobile-metric-grid {{
        border-top: 1px solid var(--line);
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 0;
      }}
      .mobile-metric-grid div {{
        border-bottom: 1px solid var(--line);
        display: grid;
        gap: 3px;
        min-height: 49px;
        padding: 8px 4px;
      }}
      .mobile-metric-grid div:nth-child(odd) {{
        border-right: 1px solid var(--line);
        padding-right: 9px;
      }}
      .mobile-metric-grid div:nth-child(even) {{
        padding-left: 9px;
      }}
      .mobile-metric-grid span,
      .mobile-card-foot {{
        color: var(--muted);
        font-size: 12px;
      }}
      .mobile-metric-grid strong {{
        color: var(--ink);
        font-family: var(--font-data);
        font-size: 14px;
        font-weight: 600;
      }}
      .mobile-card-foot {{
        display: flex;
        flex-wrap: wrap;
        gap: 6px 8px;
        line-height: 1.45;
      }}
      .mobile-card-foot > span:not(.tag) {{
        border: 1px solid var(--line);
        color: var(--ink-soft);
        padding: 2px 6px;
      }}
      .table-wrap {{
        max-height: none;
        min-height: 0;
      }}
      table {{ min-width: 1320px; font-size: 12px; }}
      th, td, .sort-button {{ padding: 8px 9px; }}
      .fund-cell {{ min-width: 180px; }}
      .rule-line {{ grid-template-columns: 1fr; gap: 2px; }}
      .tracking-overview-grid {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
      .tracking-overview-card {{
        border-left: 0;
        padding: 10px 11px;
      }}
      .tracking-overview-card:nth-child(even) {{
        border-left: 1px solid var(--line);
      }}
      .tracking-overview-card strong {{
        font-size: 15px;
        overflow: visible;
        text-overflow: clip;
        white-space: nowrap;
      }}
      .tracking-overview-card:first-child strong {{
        white-space: normal;
      }}
      .tracking-metrics {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        width: 100%;
      }}
      .tracking-metric {{
        align-items: flex-start;
        display: grid;
        gap: 2px;
        min-width: 0;
        white-space: normal;
      }}
      .tracking-metric strong {{
        line-height: 1.25;
      }}
      .tracking-subtabs {{
        flex-wrap: nowrap;
        overflow-x: auto;
        padding: 7px 10px;
        scrollbar-width: none;
      }}
      .tracking-subtabs::-webkit-scrollbar {{ display: none; }}
      .tracking-subtab {{
        flex: 0 0 auto;
        padding-left: 11px;
        padding-right: 11px;
      }}
      .tracking-overview-card + .tracking-overview-card {{ border-left: 0; }}
      .portfolio-table {{ min-width: 0; font-size: 12px; }}
      .portfolio-table th,
      .portfolio-table td {{
        padding-left: 7px;
        padding-right: 7px;
      }}
      .portfolio-table col.record-col {{ width: 8%; }}
      .portfolio-table col.rating-col {{ width: 18%; }}
      .holding-table col.holding-fund-col {{ width: 30%; }}
      .holding-table col.holding-amount-col {{ width: 21%; }}
      .holding-table col.holding-status-col {{ width: 23%; }}
      .auto-plan-table col.record-col {{ width: 7%; }}
      .auto-plan-table col.auto-fund-col {{ width: 23%; }}
      .auto-plan-table col.auto-status-col {{ width: 18%; }}
      .auto-plan-table col.auto-amount-col {{ width: 20%; }}
      .auto-plan-table col.auto-holding-col {{ width: 16%; }}
      #panel-portfolio .table-wrap,
      #panel-tracking .compact-table-wrap,
      #panel-scoring .scoring-wrap,
      #panel-sources .table-wrap {{
        overflow: visible;
      }}
      #panel-portfolio .portfolio-table,
      #panel-tracking .tracking-table,
      #panel-scoring .scoring-table,
      #panel-sources .small-table {{
        display: block;
        min-width: 0;
        width: 100%;
      }}
      #panel-portfolio .portfolio-table colgroup,
      #panel-tracking .tracking-table colgroup,
      #panel-scoring .scoring-table colgroup,
      #panel-sources .small-table colgroup,
      #panel-portfolio .portfolio-table thead,
      #panel-tracking .tracking-table thead,
      #panel-scoring .scoring-table thead,
      #panel-sources .small-table thead {{
        display: none;
      }}
      #panel-portfolio .portfolio-table tbody,
      #panel-tracking .tracking-table tbody,
      #panel-scoring .scoring-table tbody,
      #panel-sources .small-table tbody {{
        display: grid;
        gap: 8px;
        padding: 8px;
      }}
      #panel-portfolio .portfolio-table tr,
      #panel-tracking .tracking-table tr,
      #panel-scoring .scoring-table tr,
      #panel-sources .small-table tr {{
        border: 1px solid var(--line);
        background: var(--panel);
        display: grid;
        min-width: 0;
      }}
      #panel-portfolio .portfolio-table tr:nth-child(even),
      #panel-tracking .tracking-table tr:nth-child(even),
      #panel-scoring .scoring-table tr:nth-child(even),
      #panel-sources .small-table tr:nth-child(even) {{
        background: #f7f5ee;
      }}
      #panel-portfolio .portfolio-table td,
      #panel-tracking .tracking-table td,
      #panel-scoring .scoring-table td,
      #panel-sources .small-table td {{
        align-items: center;
        background: transparent !important;
        border-bottom: 1px solid var(--line);
        display: grid;
        gap: 8px;
        grid-template-columns: minmax(70px, 0.34fr) minmax(0, 1fr);
        min-width: 0;
        overflow: visible;
        overflow-wrap: anywhere;
        padding: 8px 10px;
        text-align: left;
        white-space: normal;
      }}
      #panel-portfolio .portfolio-table td:last-child,
      #panel-tracking .tracking-table td:last-child,
      #panel-scoring .scoring-table td:last-child,
      #panel-sources .small-table td:last-child {{
        border-bottom: 0;
      }}
      #panel-portfolio .portfolio-table td::before,
      #panel-tracking .tracking-table td::before,
      #panel-scoring .scoring-table td::before,
      #panel-sources .small-table td::before {{
        color: var(--muted);
        content: attr(data-label);
        font-family: var(--font-data);
        font-size: 12px;
        font-weight: 500;
        line-height: 1.35;
      }}
      #panel-portfolio .portfolio-table td > *,
      #panel-tracking .tracking-table td > *,
      #panel-scoring .scoring-table td > *,
      #panel-sources .small-table td > * {{
        min-width: 0;
      }}
      #panel-portfolio .portfolio-table .num,
      #panel-tracking .tracking-table .num,
      #panel-scoring .scoring-table .num,
      #panel-sources .small-table .num {{
        text-align: left;
        white-space: normal;
      }}
      #panel-portfolio .portfolio-table .record-index,
      #panel-tracking .tracking-table .record-index {{
        width: auto;
        min-width: 0;
      }}
      #panel-portfolio .portfolio-table .tier-pill,
      #panel-tracking .tracking-table .tier-pill {{
        justify-self: start;
        min-width: 0;
      }}
      #panel-sources .small-table td:nth-child(2),
      #panel-scoring .scoring-table td:nth-child(5) {{
        align-items: start;
        line-height: 1.55;
      }}
      .chart-frame {{
        min-height: 0;
        padding: 10px;
      }}
      .tracking-chart-svg {{
        min-height: 180px;
      }}
    }}
  </style>
</head>
<body>
  <div class="studio-shell">
    <div class="studio-main">
      <main class="page">
      <div class="artifact">
    <header class="app-header">
      <div class="title-lockup">
        <h1>纳指 <span class="title-number">100</span> A 类基金池</h1>
        <p class="subtitle">
          <span class="subtitle-chip">{len(funds)} 支</span>
          <span class="subtitle-chip">QDII</span>
          <span class="subtitle-chip">长期定投</span>
          <span class="subtitle-chip">CNY</span>
          <span class="subtitle-meta">最近更新：{data_text(generated_at)} · 自动刷新 {data_text(refresh_schedule_text)}</span>
          <span class="subtitle-meta">来源：东方财富移动接口 / 天天基金费率页 / 基金公司公告</span>
        </p>
      </div>
      <div class="header-actions">
        <div class="header-control-bar">
          <nav class="tabs" aria-label="表格页签">
            <button class="tab-button" type="button" role="tab" id="tab-main" aria-controls="panel-main" aria-selected="true">主表</button>
            <button class="tab-button" type="button" role="tab" id="tab-portfolio" aria-controls="panel-portfolio" aria-selected="false">持仓定投</button>
            <button class="tab-button" type="button" role="tab" id="tab-tracking" aria-controls="panel-tracking" aria-selected="false">长期追踪</button>
            <button class="tab-button" type="button" role="tab" id="tab-scoring" aria-controls="panel-scoring" aria-selected="false">梯队评级规则</button>
            <button class="tab-button" type="button" role="tab" id="tab-sources" aria-controls="panel-sources" aria-selected="false">数据来源</button>
          </nav>
        </div>
      </div>
    </header>

    <section class="section tab-panel" id="panel-main" role="tabpanel" aria-labelledby="tab-main">
      <div class="table-toolbar">
        <div class="table-controls">
          <div class="filter-control">
            <span class="filter-label">定投状态</span>
            <div class="select-menu" id="status-filter" data-filter-key="status">
              <button class="select-trigger" type="button" aria-haspopup="listbox" aria-expanded="false">全部状态</button>
              <ul class="select-list" role="listbox" hidden>
                <li class="select-option" role="option" data-value="all" aria-selected="true">全部状态</li>
                <li class="select-option" role="option" data-value="active-investing" aria-selected="false">定投中（含新增）</li>
                <li class="select-option" role="option" data-value="新增定投" aria-selected="false">新增定投</li>
                <li class="select-option" role="option" data-value="暂停定投" aria-selected="false">暂停定投</li>
                <li class="select-option" role="option" data-value="候选" aria-selected="false">候选</li>
              </ul>
            </div>
          </div>
          <div class="filter-control">
            <span class="filter-label">梯队</span>
            <div class="select-menu" id="tier-filter" data-filter-key="tier">
              <button class="select-trigger" type="button" aria-haspopup="listbox" aria-expanded="false">全部梯队</button>
              <ul class="select-list" role="listbox" hidden>
                <li class="select-option" role="option" data-value="all" aria-selected="true">全部梯队</li>
                <li class="select-option" role="option" data-value="S" aria-selected="false">S 档</li>
                <li class="select-option" role="option" data-value="A" aria-selected="false">A 档</li>
                <li class="select-option" role="option" data-value="B" aria-selected="false">B 档</li>
                <li class="select-option" role="option" data-value="C" aria-selected="false">C 档</li>
                <li class="select-option" role="option" data-value="D" aria-selected="false">D 档</li>
              </ul>
            </div>
          </div>
          <div class="filter-control">
            <span class="filter-label">申购状态</span>
            <div class="select-menu" id="subscription-filter" data-filter-key="subscription">
              <button class="select-trigger" type="button" aria-haspopup="listbox" aria-expanded="false">全部申购</button>
              <ul class="select-list" role="listbox" hidden>
                <li class="select-option" role="option" data-value="all" aria-selected="true">全部申购</li>
                <li class="select-option" role="option" data-value="限大额" aria-selected="false">限大额</li>
                <li class="select-option" role="option" data-value="暂停申购" aria-selected="false">暂停申购</li>
                <li class="select-option" role="option" data-value="开放申购" aria-selected="false">开放申购</li>
              </ul>
            </div>
          </div>
          <div class="column-menu" id="column-menu">
            <button class="ghost-button" type="button" id="column-toggle" aria-haspopup="true" aria-expanded="false">列定制</button>
            <div class="column-panel" id="column-panel" hidden>
              <div class="column-panel-head">
                <span class="column-panel-title">选择显示列</span>
                <button class="column-reset" type="button" id="column-reset">恢复默认</button>
              </div>
              <div class="column-options" id="column-options"></div>
            </div>
          </div>
          <button class="ghost-button" type="button" id="reset-filters">重置</button>
        </div>
        <div class="visible-count" id="visible-count">显示 {data_text(len(funds))} / {data_text(len(funds))} 支</div>
      </div>
      <div class="table-wrap">
        <table id="main-table">
          <colgroup>
            <col class="rank-col">
            <col class="tier-col">
            <col class="fund-col">
            <col class="position-col">
            <col class="return-col">
            <col class="return-col">
            <col class="tracking-col">
            <col class="fee-col">
            <col class="size-col">
            <col class="fee-col">
            <col class="fee-col">
            <col class="status-detail-col">
            <col class="limit-col">
            <col class="limit-col">
            <col class="detail-col">
            <col class="rules-col">
            <col class="return-col">
            <col class="status-col">
          </colgroup>
          <thead>
            <tr>
              <th>排名</th>
              <th class="sortable" data-column-index="1" data-sort-type="number"><button type="button" class="sort-button">定投梯队<span class="sort-indicator"></span></button></th>
              <th class="sortable" data-column-index="2" data-sort-type="text"><button type="button" class="sort-button">基金 / 代码<span class="sort-indicator"></span></button></th>
              <th class="sortable" data-column-index="3" data-sort-type="number"><button type="button" class="sort-button">持仓 / 定投<span class="sort-indicator"></span></button></th>
              <th class="sortable" data-column-index="4" data-sort-type="number"><button type="button" class="sort-button">近3年<span class="sort-indicator"></span></button></th>
              <th class="sortable" data-column-index="5" data-sort-type="number"><button type="button" class="sort-button">近1年<span class="sort-indicator"></span></button></th>
              <th class="sortable" data-column-index="6" data-sort-type="number"><button type="button" class="sort-button">跟踪误差<span class="sort-indicator"></span></button></th>
              <th class="sortable" data-column-index="7" data-sort-type="number"><button type="button" class="sort-button">管理+托管<span class="sort-indicator"></span></button></th>
              <th class="sortable" data-column-index="8" data-sort-type="number"><button type="button" class="sort-button">规模<span class="sort-indicator"></span></button></th>
              <th class="sortable" data-column-index="9" data-sort-type="number"><button type="button" class="sort-button">买入费率<span class="sort-indicator"></span></button></th>
              <th class="sortable" data-column-index="10" data-sort-type="number"><button type="button" class="sort-button">免赎回费门槛<span class="sort-indicator"></span></button></th>
              <th class="sortable" data-column-index="11" data-sort-type="number"><button type="button" class="sort-button">申购状态<span class="sort-indicator"></span></button></th>
              <th class="sortable" data-column-index="12" data-sort-type="number"><button type="button" class="sort-button">代销限额<span class="sort-indicator"></span></button></th>
              <th class="sortable" data-column-index="13" data-sort-type="number"><button type="button" class="sort-button">直销限额<span class="sort-indicator"></span></button></th>
              <th>费率项目</th>
              <th class="sortable" data-column-index="15" data-sort-type="number"><button type="button" class="sort-button">卖出规则<span class="sort-indicator"></span></button></th>
              <th class="sortable" data-column-index="16" data-sort-type="number"><button type="button" class="sort-button">日涨跌<span class="sort-indicator"></span></button></th>
              <th class="sortable" data-column-index="17" data-sort-type="number"><button type="button" class="sort-button">定投状态<span class="sort-indicator"></span></button></th>
            </tr>
          </thead>
          <tbody>
{rows}
          </tbody>
        </table>
      </div>
      <div class="mobile-fund-list" id="mobile-fund-list" aria-label="手机基金列表">
{mobile_cards}
      </div>
    </section>

    <section class="section tab-panel" id="panel-portfolio" role="tabpanel" aria-labelledby="tab-portfolio" hidden>
      <div class="portfolio-grid">
        <div class="portfolio-block">
          <div class="section-title"><h2>当前持有</h2><span class="title-metric">总额 <strong id="holding-total-value">{fmt_yuan(holding_total)}</strong></span></div>
          <div class="table-wrap compact-table-wrap">
            <table class="small-table portfolio-table holding-table">
              <colgroup>
                <col class="record-col">
                <col class="holding-fund-col">
                <col class="rating-col">
                <col class="holding-amount-col">
                <col class="holding-status-col">
              </colgroup>
              <thead><tr><th>序号</th><th>基金</th><th>评级</th><th>持有金额</th><th>定投状态</th></tr></thead>
              <tbody>{holding_rows}</tbody>
            </table>
          </div>
        </div>
        <div class="portfolio-block">
          <div class="section-title"><h2>定投计划</h2><span class="title-metric">定投中总额 <strong id="active-auto-total-value">{fmt_yuan(active_auto_invest_total)} / 期</strong></span></div>
          <div class="table-wrap compact-table-wrap">
            <table class="small-table portfolio-table auto-plan-table">
              <colgroup>
                <col class="record-col">
                <col class="auto-fund-col">
                <col class="rating-col">
                <col class="auto-status-col">
                <col class="auto-amount-col">
                <col class="auto-holding-col">
              </colgroup>
              <thead><tr><th>序号</th><th>基金</th><th>评级</th><th>状态</th><th>金额</th><th>当前持有</th></tr></thead>
              <tbody>{auto_invest_rows}</tbody>
            </table>
          </div>
        </div>
      </div>
    </section>

    <section class="section tab-panel" id="panel-tracking" role="tabpanel" aria-labelledby="tab-tracking" hidden>
      <div class="section-title tracking-head">
        <div class="title-copy">
          <h2>长期追踪</h2>
        </div>
        <div class="tracking-metrics">
          <span class="tracking-metric">最近记录 <strong>{data_text(tracking_latest_date)}</strong></span>
          <span class="tracking-metric">记录数 <strong>{data_text(tracking_count)}</strong></span>
          <span class="tracking-metric">当前持有 <strong>{fmt_yuan(holding_total)}</strong></span>
          <span class="tracking-metric">定投中 <strong>{fmt_yuan(active_auto_invest_total)} / 期</strong></span>
          <span class="tracking-metric">暂停 <strong>{fmt_yuan(paused_auto_invest_total)} / 期</strong></span>
        </div>
      </div>
      <div class="tracking-subtabs" role="tablist" aria-label="长期追踪视图">
        <button class="tracking-subtab" type="button" role="tab" id="tracking-tab-overview" aria-controls="tracking-panel-overview" aria-selected="true">总览</button>
        <button class="tracking-subtab" type="button" role="tab" id="tracking-tab-trend" aria-controls="tracking-panel-trend" aria-selected="false">趋势</button>
        <button class="tracking-subtab" type="button" role="tab" id="tracking-tab-years" aria-controls="tracking-panel-years" aria-selected="false">年度</button>
        <button class="tracking-subtab" type="button" role="tab" id="tracking-tab-allocation" aria-controls="tracking-panel-allocation" aria-selected="false">结构</button>
        <button class="tracking-subtab" type="button" role="tab" id="tracking-tab-funds" aria-controls="tracking-panel-funds" aria-selected="false">明细</button>
        <button class="tracking-subtab" type="button" role="tab" id="tracking-tab-snapshots" aria-controls="tracking-panel-snapshots" aria-selected="false">快照</button>
      </div>
      <div class="tracking-subpanel" id="tracking-panel-overview" role="tabpanel" aria-labelledby="tracking-tab-overview">
        <div class="tracking-overview-panel">
          <div class="tracking-overview-grid">
            <div class="tracking-overview-card"><span>追踪区间</span><strong>{tracking_span}</strong></div>
            <div class="tracking-overview-card"><span>历史快照</span><strong>{data_text(tracking_count)} 条</strong></div>
            <div class="tracking-overview-card"><span>覆盖年份</span><strong>{data_text(tracking_year_count)} 年</strong></div>
            <div class="tracking-overview-card"><span>当前基线</span><strong>{data_text(tracking_visible_count)} 支</strong></div>
          </div>
          <div class="tracking-chart-stack">
            <div class="tracking-chart-card">
              <div class="section-title"><h2>资产轨迹</h2><span class="title-metric">持有记录 / 市值</span></div>
              <div class="chart-frame">{tracking_asset_chart}</div>
            </div>
            <div class="tracking-chart-card">
              <div class="section-title"><h2>收益轨迹</h2><span class="title-metric">收益 / 收益率</span></div>
              <div class="chart-frame">{tracking_return_chart}</div>
            </div>
          </div>
        </div>
      </div>
      <div class="tracking-subpanel" id="tracking-panel-trend" role="tabpanel" aria-labelledby="tracking-tab-trend" hidden>
        <div class="tracking-chart-stack tracking-wide-stack">
          <div class="tracking-chart-card">
            <div class="section-title"><h2>资产轨迹</h2><span class="title-metric">持有记录 / 市值</span></div>
            <div class="chart-frame">{tracking_asset_chart}</div>
          </div>
          <div class="tracking-chart-card">
            <div class="section-title"><h2>收益轨迹</h2><span class="title-metric">收益 / 收益率</span></div>
            <div class="chart-frame">{tracking_return_chart}</div>
          </div>
        </div>
      </div>
      <div class="tracking-subpanel" id="tracking-panel-years" role="tabpanel" aria-labelledby="tracking-tab-years" hidden>
        <div class="tracking-single-panel">
          <div class="tracking-block">
            <div class="section-title"><h2>年度复盘</h2><span class="title-metric">按年份聚合所有快照</span></div>
            <div class="table-wrap compact-table-wrap">
              <table class="small-table tracking-table tracking-year-table">
                <colgroup>
                  <col class="year-col">
                  <col class="count-col">
                  <col class="date-col">
                  <col class="date-col">
                  <col class="amount-col">
                  <col class="amount-col">
                  <col class="amount-col">
                  <col class="amount-col">
                  <col class="amount-col">
                </colgroup>
                <thead><tr><th>年份</th><th>记录</th><th>首条</th><th>末条</th><th>持有变化</th><th>期末持有</th><th>期末市值</th><th>期末收益</th><th>收益率</th></tr></thead>
                <tbody>{tracking_year_table_rows}</tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
      <div class="tracking-subpanel" id="tracking-panel-allocation" role="tabpanel" aria-labelledby="tracking-tab-allocation" hidden>
        <div class="tracking-single-panel">
          <div class="tracking-allocation-card">
            <div class="section-title"><h2>持仓结构</h2><span class="title-metric">按当前持有金额</span></div>
            <div class="allocation-list">{tracking_allocation}</div>
          </div>
        </div>
      </div>
      <div class="tracking-subpanel" id="tracking-panel-funds" role="tabpanel" aria-labelledby="tracking-tab-funds" hidden>
        <div class="tracking-single-panel">
          <div class="tracking-block">
            <div class="section-title"><h2>基金追踪</h2><span class="title-metric">当前基线 <strong>{data_text(tracking_visible_count)}</strong> 支</span></div>
            <div class="table-wrap compact-table-wrap">
              <table class="small-table tracking-table tracking-fund-table">
                <colgroup>
                  <col class="record-col">
                  <col class="fund-col-small">
                  <col class="rating-col">
                  <col class="amount-col">
                  <col class="plan-col">
                  <col class="amount-col">
                  <col class="amount-col">
                  <col class="amount-col">
                </colgroup>
                <thead><tr><th>序号</th><th>基金</th><th>评级</th><th>持有</th><th>定投</th><th>市值</th><th>收益</th><th>收益率</th></tr></thead>
                <tbody>{tracking_detail_table_rows}</tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
      <div class="tracking-subpanel" id="tracking-panel-snapshots" role="tabpanel" aria-labelledby="tracking-tab-snapshots" hidden>
        <div class="tracking-single-panel">
          <div class="tracking-block">
            <div class="section-title"><h2>追踪快照</h2><span class="title-metric">累计 <strong>{data_text(tracking_count)}</strong> 条</span></div>
            <div class="table-wrap compact-table-wrap">
              <table class="small-table tracking-table tracking-history-table">
                <colgroup>
                  <col class="record-col">
                  <col class="date-col">
                  <col class="amount-col">
                  <col class="amount-col">
                  <col class="amount-col">
                  <col class="amount-col">
                  <col class="amount-col">
                </colgroup>
                <thead><tr><th>序号</th><th>日期</th><th>持有</th><th>定投中</th><th>市值</th><th>收益</th><th>收益率</th></tr></thead>
                <tbody>{tracking_snapshot_table_rows}</tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="section tab-panel" id="panel-scoring" role="tabpanel" aria-labelledby="tab-scoring" hidden>
      <div class="section-title">
        <div class="title-copy">
          <h2>梯队评级规则</h2>
          <span class="hint">收益优先模型：先看历史收益、跟踪质量和持续费用，再用规模、买入费率和赎回灵活性做轻量校正。</span>
        </div>
      </div>
      <div class="table-wrap scoring-wrap">
        <table class="small-table scoring-table">
          <thead><tr><th>指标</th><th>权重</th><th>方向</th><th>计算口径</th><th>纳入评级的理由</th></tr></thead>
          <tbody>{scoring_rows}</tbody>
        </table>
      </div>
      <div class="notes">
        <p>梯队划分采用分位：S 为当前池内最前约 10%，A 为随后约 22.5%，B 为中间约 35%，C 为随后约 22.5%，D 为最后约 10%。样本数量较少时，梯队是“当前候选池内相对位置”，不是市场通用评级。</p>
        <p>收益相关指标合计 55%（近3年 35% + 近1年 20%），跟踪误差和管理+托管费合计 35%。申购状态和限额只作为筛选与交易执行信息，不参与梯队评级。</p>
      </div>
    </section>

    <section class="section tab-panel" id="panel-sources" role="tabpanel" aria-labelledby="tab-sources" hidden>
      <div class="section-title"><h2>数据来源</h2><span class="hint">每只基金抓取状态。</span></div>
      <div class="table-wrap">
        <table class="small-table source-table">
          <thead><tr><th>代码</th><th>来源状态</th></tr></thead>
          <tbody>{source_rows}</tbody>
        </table>
      </div>
    </section>
      </div>
      </main>
    </div>
  </div>
  <div id="portfolio-editor" class="portfolio-editor" hidden></div>
  <script>
    (function () {{
      const initialPortfolioState = {portfolio_state_json};
      const portfolioStorageKey = "nasdaqFundPortfolioStateV1";
      const tabButtons = Array.from(document.querySelectorAll(".tab-button"));
      const tabPanels = Array.from(document.querySelectorAll(".tab-panel"));
      tabButtons.forEach((button) => {{
        button.addEventListener("click", () => {{
          const targetPanel = button.getAttribute("aria-controls");
          tabButtons.forEach((item) => item.setAttribute("aria-selected", item.getAttribute("aria-controls") === targetPanel ? "true" : "false"));
          tabPanels.forEach((panel) => {{
            panel.hidden = panel.id !== targetPanel;
          }});
        }});
      }});
      const trackingSubtabs = Array.from(document.querySelectorAll(".tracking-subtab"));
      const trackingSubpanels = Array.from(document.querySelectorAll(".tracking-subpanel"));
      trackingSubtabs.forEach((button) => {{
        button.addEventListener("click", () => {{
          const targetPanel = button.getAttribute("aria-controls");
          trackingSubtabs.forEach((item) => item.setAttribute("aria-selected", item === button ? "true" : "false"));
          trackingSubpanels.forEach((panel) => {{
            panel.hidden = panel.id !== targetPanel;
          }});
        }});
      }});
      const table = document.getElementById("main-table");
      if (!table) return;
      const headers = Array.from(table.querySelectorAll("th.sortable"));
      const tbody = table.querySelector("tbody");
      const filters = {{ status: "all", tier: "all", subscription: "all" }};
      const filterMenus = Array.from(document.querySelectorAll(".select-menu[data-filter-key]"));
      const resetButton = document.getElementById("reset-filters");
      const visibleCount = document.getElementById("visible-count");
      const columnMenu = document.getElementById("column-menu");
      const columnToggle = document.getElementById("column-toggle");
      const columnPanel = document.getElementById("column-panel");
      const columnOptions = document.getElementById("column-options");
      const columnReset = document.getElementById("column-reset");
      const portfolioEditor = document.getElementById("portfolio-editor");
      const mobileFundList = document.getElementById("mobile-fund-list");
      const tableColumns = Array.from(table.querySelectorAll("colgroup col"));
      const allHeaderCells = Array.from(table.querySelectorAll("thead th"));
      const lockedColumnIndexes = new Set([0, 1, 2, 3]);
      const defaultVisibleColumns = new Set(Array.from({{ length: allHeaderCells.length }}, (_, index) => index));
      const columnStorageKey = "nasdaqFundVisibleColumnsV3";
      const totalRows = tbody ? tbody.querySelectorAll("tr").length : 0;
      let activeIndex = 0;
      let activeDirection = "desc";
      function normalizeAmount(value) {{
        const number = Number(String(value ?? "").replace(/[^0-9.]/g, ""));
        if (!Number.isFinite(number) || number < 0) return 0;
        return Math.round(number * 100) / 100;
      }}
      function formatYuan(value) {{
        const amount = normalizeAmount(value);
        return amount % 1 === 0 ? `${{amount.toFixed(0)}}元` : `${{amount.toFixed(2).replace(/0+$/, "").replace(/[.]$/, "")}}元`;
      }}
      function dataText(value) {{
        return `<span class="data-text">${{value}}</span>`;
      }}
      function tagClass(status) {{
        if (status === "定投中" || status === "新增定投") return "owned";
        if (status === "暂停定投") return "paused";
        if (status === "已持有") return "info";
        return "watch";
      }}
      function statusRank(status) {{
        const order = {{ "新增定投": 0, "定投中": 1, "暂停定投": 2, "已持有": 3, "候选": 4 }};
        return order[status] ?? 9;
      }}
      function statusTag(status) {{
        return `<span class="tag ${{tagClass(status)}}">${{status}}</span>`;
      }}
      function cloneInitialPortfolioState() {{
        return Object.fromEntries(Object.entries(initialPortfolioState).map(([code, item]) => [
          code,
          {{
            label: item.label || code,
            holding: normalizeAmount(item.holding),
            active: normalizeAmount(item.active),
            paused: normalizeAmount(item.paused),
          }},
        ]));
      }}
      function readPortfolioState() {{
        const state = cloneInitialPortfolioState();
        try {{
          const raw = localStorage.getItem(portfolioStorageKey);
          if (!raw) return state;
          const saved = JSON.parse(raw);
          if (!saved || typeof saved !== "object") return state;
          Object.entries(saved).forEach(([code, item]) => {{
            if (!state[code] || !item || typeof item !== "object") return;
            state[code].holding = normalizeAmount(item.holding);
            state[code].active = normalizeAmount(item.active);
            state[code].paused = normalizeAmount(item.paused);
          }});
        }} catch (error) {{}}
        return state;
      }}
      let portfolioState = readPortfolioState();
      function savePortfolioState() {{
        try {{
          localStorage.setItem(portfolioStorageKey, JSON.stringify(portfolioState));
        }} catch (error) {{}}
      }}
      function currentStatus(item) {{
        if (item.active > 0) return "定投中";
        if (item.paused > 0) return "暂停定投";
        if (item.holding > 0) return "已持有";
        return "候选";
      }}
      function planAmount(item) {{
        return item.active > 0 ? item.active : item.paused;
      }}
      function planText(item) {{
        if (item.active > 0) return `定投中 · ${{formatYuan(item.active)}} / 期`;
        if (item.paused > 0) return `已暂停 · ${{formatYuan(item.paused)}} / 期`;
        return "未设置";
      }}
      function updateTitleTotals() {{
        const holdingTotal = Object.values(portfolioState).reduce((sum, item) => sum + normalizeAmount(item.holding), 0);
        const activeTotal = Object.values(portfolioState).reduce((sum, item) => sum + normalizeAmount(item.active), 0);
        const holdingTotalNode = document.getElementById("holding-total-value");
        const activeTotalNode = document.getElementById("active-auto-total-value");
        if (holdingTotalNode) holdingTotalNode.innerHTML = dataText(formatYuan(holdingTotal));
        if (activeTotalNode) activeTotalNode.innerHTML = `${{dataText(formatYuan(activeTotal))}} / 期`;
      }}
      function updateMobileCard(code) {{
        if (!mobileFundList) return;
        const item = portfolioState[code];
        const card = mobileFundList.querySelector(`[data-mobile-card][data-code="${{code}}"]`);
        if (!item || !card) return;
        const status = currentStatus(item);
        card.dataset.status = status;
        const statusNode = card.querySelector(".mobile-status");
        if (statusNode) {{
          statusNode.className = `tag ${{tagClass(status)}} mobile-status`;
          statusNode.textContent = status;
        }}
        const lines = card.querySelectorAll(".mobile-position-lines strong");
        if (lines[0]) lines[0].innerHTML = item.holding > 0 ? dataText(formatYuan(item.holding)) : dataText("0元");
        if (lines[1]) {{
          if (item.active > 0) lines[1].innerHTML = `${{dataText(formatYuan(item.active))}} / 期`;
          else if (item.paused > 0) lines[1].innerHTML = `暂停 ${{dataText(formatYuan(item.paused))}} / 期`;
          else lines[1].textContent = "未设置";
        }}
      }}
      function updateMainRow(code) {{
        const item = portfolioState[code];
        const row = table.querySelector(`tbody tr[data-code="${{code}}"]`);
        if (!item || !row) return;
        const status = currentStatus(item);
        row.dataset.status = status;
        row.dataset.holdingAmount = String(item.holding);
        row.dataset.autoInvestAmount = String(item.active);
        row.dataset.pausedAutoInvestAmount = String(item.paused);
        const statusCell = row.children[17];
        if (statusCell) {{
          statusCell.dataset.sortValue = String(statusRank(status));
          statusCell.innerHTML = statusTag(status);
        }}
        const positionCell = row.children[3];
        if (positionCell) {{
          const positionSort = item.holding * 1000000 + item.active * 1000 + item.paused;
          positionCell.dataset.sortValue = String(positionSort);
          const holdingLine = item.holding > 0
            ? `<span class="position-line"><em>持有</em><strong>${{dataText(formatYuan(item.holding))}}</strong></span>`
            : `<span class="position-line muted-line"><em>持有</em><strong>0元</strong></span>`;
          const investLine = item.active > 0
            ? `<span class="position-line"><em>定投</em><strong>${{dataText(formatYuan(item.active))}} / 期</strong></span>`
            : item.paused > 0
              ? `<span class="position-line paused-line"><em>暂停</em><strong>${{dataText(formatYuan(item.paused))}} / 期</strong></span>`
              : `<span class="position-line muted-line"><em>定投</em><strong>未设置</strong></span>`;
          positionCell.innerHTML = `<div class="position-plan">${{holdingLine}}${{investLine}}</div>`;
        }}
      }}
      function updateHoldingRows() {{
        document.querySelectorAll(".holding-table tbody tr[data-code]").forEach((row) => {{
          const code = row.dataset.code;
          const item = portfolioState[code];
          if (!item) return;
          const status = currentStatus(item);
          const holdingCell = row.querySelector('[data-field="holding"]');
          const statusCell = row.querySelector('[data-field="status"]');
          if (holdingCell) {{
            holdingCell.dataset.sortValue = String(item.holding);
            holdingCell.innerHTML = dataText(formatYuan(item.holding));
          }}
          if (statusCell) statusCell.innerHTML = statusTag(status);
        }});
      }}
      function updateAutoRows() {{
        document.querySelectorAll(".auto-plan-table tbody tr[data-code]").forEach((row) => {{
          const code = row.dataset.code;
          const item = portfolioState[code];
          if (!item) return;
          const status = currentStatus(item);
          const statusCell = row.querySelector('[data-field="status"]');
          const amountCell = row.querySelector('[data-field="plan_amount"]');
          const holdingCell = row.querySelector('[data-field="holding"]');
          if (statusCell) statusCell.innerHTML = statusTag(status);
          if (amountCell) {{
            const amount = planAmount(item);
            amountCell.dataset.sortValue = String(amount);
            amountCell.innerHTML = `${{dataText(formatYuan(amount))}} / 期`;
          }}
          if (holdingCell) {{
            holdingCell.dataset.sortValue = String(item.holding);
            holdingCell.innerHTML = dataText(formatYuan(item.holding));
          }}
        }});
      }}
      function refreshPortfolioViews() {{
        Object.keys(portfolioState).forEach((code) => updateMainRow(code));
        Object.keys(portfolioState).forEach((code) => updateMobileCard(code));
        updateHoldingRows();
        updateAutoRows();
        updateTitleTotals();
        sortByHeader(activeIndex, activeDirection);
      }}
      function setPlanStatus(code, status) {{
        const item = portfolioState[code];
        if (!item) return;
        const amount = planAmount(item) || 10;
        if (status === "定投中") {{
          item.active = amount;
          item.paused = 0;
        }} else if (status === "暂停定投") {{
          item.paused = amount;
          item.active = 0;
        }} else {{
          item.active = 0;
          item.paused = 0;
        }}
        savePortfolioState();
        refreshPortfolioViews();
      }}
      function setAmount(code, field, value) {{
        const item = portfolioState[code];
        if (!item) return;
        const amount = normalizeAmount(value);
        if (field === "holding") item.holding = amount;
        if (field === "plan_amount") {{
          if (item.active > 0 || item.paused === 0) item.active = amount;
          else item.paused = amount;
          if (amount === 0) {{
            item.active = 0;
            item.paused = 0;
          }}
        }}
        savePortfolioState();
        refreshPortfolioViews();
      }}
      let activeEditorCell = null;
      function closePortfolioEditor() {{
        if (!portfolioEditor) return;
        portfolioEditor.hidden = true;
        portfolioEditor.replaceChildren();
        activeEditorCell = null;
      }}
      function placePortfolioEditor(cell) {{
        if (!portfolioEditor) return;
        const rect = cell.getBoundingClientRect();
        const width = portfolioEditor.offsetWidth || 270;
        const topGap = 7;
        const left = Math.min(Math.max(12, rect.left), window.innerWidth - width - 12);
        let top = rect.bottom + topGap;
        const editorHeight = portfolioEditor.offsetHeight || 120;
        if (top + editorHeight > window.innerHeight - 12) {{
          top = Math.max(12, rect.top - editorHeight - topGap);
        }}
        portfolioEditor.style.left = `${{Math.round(left)}}px`;
        portfolioEditor.style.top = `${{Math.round(top)}}px`;
      }}
      function openAmountEditor(cell) {{
        const row = cell.closest("tr[data-code]");
        const code = row?.dataset.code;
        const field = cell.dataset.field;
        const item = code ? portfolioState[code] : null;
        if (!item || !field || !portfolioEditor) return;
        const currentValue = field === "holding" ? item.holding : planAmount(item);
        activeEditorCell = cell;
        portfolioEditor.hidden = false;
        portfolioEditor.innerHTML = `
          <div class="editor-panel" role="dialog" aria-label="修改金额">
            <div class="editor-row">
              <input class="editor-input" type="number" min="0" step="1" inputmode="decimal" value="${{currentValue}}" aria-label="金额">
              <span class="editor-suffix">元${{field === "plan_amount" ? " / 期" : ""}}</span>
            </div>
            <div class="editor-row">
              <button type="button" class="editor-action primary" data-action="commit">确定</button>
              <button type="button" class="editor-action" data-action="cancel">取消</button>
            </div>
          </div>
        `;
        placePortfolioEditor(cell);
        const input = portfolioEditor.querySelector(".editor-input");
        const commit = () => {{
          setAmount(code, field, input.value);
          closePortfolioEditor();
        }};
        portfolioEditor.querySelector('[data-action="commit"]')?.addEventListener("click", commit);
        portfolioEditor.querySelector('[data-action="cancel"]')?.addEventListener("click", closePortfolioEditor);
        input?.addEventListener("keydown", (event) => {{
          if (event.key === "Enter") {{
            event.preventDefault();
            commit();
          }}
          if (event.key === "Escape") {{
            event.preventDefault();
            closePortfolioEditor();
          }}
        }});
        requestAnimationFrame(() => {{
          placePortfolioEditor(cell);
          input?.focus();
          input?.select();
        }});
      }}
      function openStatusEditor(cell) {{
        const row = cell.closest("tr[data-code]");
        const code = row?.dataset.code;
        const item = code ? portfolioState[code] : null;
        if (!item || !portfolioEditor) return;
        const selectedStatus = currentStatus(item);
        const noPlanStatus = item.holding > 0 ? "已持有" : "候选";
        const options = ["定投中", "暂停定投", noPlanStatus];
        activeEditorCell = cell;
        portfolioEditor.hidden = false;
        portfolioEditor.innerHTML = `
          <div class="editor-panel editor-options" role="listbox" aria-label="选择定投状态">
            ${{options.map((status) => `
              <button type="button" class="editor-option" role="option" data-status="${{status}}" aria-selected="${{status === selectedStatus ? "true" : "false"}}">${{status}}</button>
            `).join("")}}
          </div>
        `;
        placePortfolioEditor(cell);
        portfolioEditor.querySelectorAll(".editor-option").forEach((option) => {{
          option.addEventListener("click", () => {{
            setPlanStatus(code, option.dataset.status || noPlanStatus);
            closePortfolioEditor();
          }});
          option.addEventListener("keydown", (event) => {{
            if (event.key === "Escape") {{
              event.preventDefault();
              closePortfolioEditor();
            }}
          }});
        }});
        requestAnimationFrame(() => {{
          placePortfolioEditor(cell);
          portfolioEditor.querySelector('[aria-selected="true"]')?.focus();
        }});
      }}
      function beginAmountEdit(cell) {{
        openAmountEditor(cell);
      }}
      function beginStatusEdit(cell) {{
        openStatusEditor(cell);
      }}
      document.addEventListener("pointerdown", (event) => {{
        if (!portfolioEditor || portfolioEditor.hidden) return;
        const target = event.target;
        if (portfolioEditor.contains(target)) return;
        if (activeEditorCell && activeEditorCell.contains(target)) return;
        closePortfolioEditor();
      }});
      document.addEventListener("keydown", (event) => {{
        if (event.key === "Escape" && portfolioEditor && !portfolioEditor.hidden) closePortfolioEditor();
      }});
      window.addEventListener("resize", closePortfolioEditor);
      window.addEventListener("scroll", closePortfolioEditor, true);
      function readValue(cell, type) {{
        const raw = (cell.dataset.sortValue || cell.textContent || "").trim();
        if (type === "number") {{
          const number = Number(raw.replace(/[,%元/年天+]/g, ""));
          return Number.isNaN(number) ? 0 : number;
        }}
        return raw.toLocaleLowerCase("zh-CN");
      }}
      function updateIndicators() {{
        headers.forEach((header, index) => {{
          const indicator = header.querySelector(".sort-indicator");
          if (!indicator) return;
          indicator.textContent = index === activeIndex ? (activeDirection === "asc" ? "↑" : "↓") : "↕";
        }});
      }}
      function updateRanks() {{
        Array.from(tbody.querySelectorAll("tr:not([hidden])")).forEach((row, index) => {{
          const rankCell = row.querySelector(".row-rank");
          if (rankCell) rankCell.textContent = String(index + 1);
          const mobileCard = mobileFundList ? mobileFundList.querySelector(`[data-mobile-card][data-code="${{row.dataset.code}}"]`) : null;
          const mobileRank = mobileCard ? mobileCard.querySelector(".mobile-rank-number") : null;
          if (mobileRank) mobileRank.innerHTML = dataText(String(index + 1));
        }});
      }}
      function updateVisibleCount() {{
        if (!visibleCount) return;
        const visible = tbody.querySelectorAll("tr:not([hidden])").length;
        visibleCount.innerHTML = `显示 <span class="data-text">${{visible}}</span> / <span class="data-text">${{totalRows}}</span> 支`;
      }}
      function dataSpan(value) {{
        return `<span class="data-text">${{value}}</span>`;
      }}
      function visibleRows() {{
        return Array.from(tbody.querySelectorAll("tr:not([hidden])"));
      }}
      function columnLabel(header) {{
        return (header.textContent || "").replace(/[↕↑↓]/g, "").trim();
      }}
      function readVisibleColumns() {{
        try {{
          const raw = localStorage.getItem(columnStorageKey);
          if (!raw) return new Set(defaultVisibleColumns);
          const values = JSON.parse(raw);
          if (!Array.isArray(values)) return new Set(defaultVisibleColumns);
          const visible = new Set(values.filter((value) => Number.isInteger(value) && value >= 0 && value < allHeaderCells.length));
          lockedColumnIndexes.forEach((index) => visible.add(index));
          return visible;
        }} catch (error) {{
          return new Set(defaultVisibleColumns);
        }}
      }}
      function saveVisibleColumns(visible) {{
        try {{
          localStorage.setItem(columnStorageKey, JSON.stringify(Array.from(visible).sort((a, b) => a - b)));
        }} catch (error) {{}}
      }}
      let visibleColumns = readVisibleColumns();
      function setColumnHidden(index, hidden) {{
        const column = tableColumns[index];
        const header = allHeaderCells[index];
        if (column) column.classList.toggle("is-column-hidden", hidden);
        if (header) header.classList.toggle("is-column-hidden", hidden);
        Array.from(tbody.querySelectorAll("tr")).forEach((row) => {{
          const cell = row.children[index];
          if (cell) cell.classList.toggle("is-column-hidden", hidden);
        }});
      }}
      function applyColumnVisibility() {{
        allHeaderCells.forEach((_, index) => {{
          const hidden = !visibleColumns.has(index);
          setColumnHidden(index, hidden);
          const checkbox = columnOptions ? columnOptions.querySelector(`input[data-column-index="${{index}}"]`) : null;
          if (checkbox) checkbox.checked = !hidden;
        }});
      }}
      function buildColumnOptions() {{
        if (!columnOptions) return;
        columnOptions.innerHTML = "";
        allHeaderCells.forEach((header, index) => {{
          const label = document.createElement("label");
          const locked = lockedColumnIndexes.has(index);
          label.className = `column-option${{locked ? " locked" : ""}}`;
          const input = document.createElement("input");
          input.type = "checkbox";
          input.dataset.columnIndex = String(index);
          input.checked = visibleColumns.has(index);
          input.disabled = locked;
          const text = document.createElement("span");
          text.textContent = columnLabel(header);
          label.append(input, text);
          if (!locked) {{
            input.addEventListener("change", () => {{
              if (input.checked) visibleColumns.add(index);
              else visibleColumns.delete(index);
              lockedColumnIndexes.forEach((lockedIndex) => visibleColumns.add(lockedIndex));
              saveVisibleColumns(visibleColumns);
              applyColumnVisibility();
            }});
          }}
          columnOptions.appendChild(label);
        }});
      }}
      function closeColumnPanel() {{
        if (columnToggle) columnToggle.setAttribute("aria-expanded", "false");
        if (columnPanel) columnPanel.hidden = true;
      }}
      function matchesStatus(rowStatus, filterValue) {{
        if (filterValue === "all") return true;
        if (filterValue === "active-investing") return rowStatus === "定投中" || rowStatus === "新增定投";
        return rowStatus === filterValue;
      }}
      function matchesSubscription(rowSubscriptionStatus, filterValue) {{
        if (filterValue === "all") return true;
        return rowSubscriptionStatus === filterValue;
      }}
      function applyFilter() {{
        Array.from(tbody.querySelectorAll("tr")).forEach((row) => {{
          const statusMatched = matchesStatus(row.dataset.status || "", filters.status);
          const tierMatched = filters.tier === "all" || row.dataset.tier === filters.tier;
          const subscriptionMatched = matchesSubscription(row.dataset.subscriptionStatus || "", filters.subscription);
          const hidden = !(statusMatched && tierMatched && subscriptionMatched);
          row.hidden = hidden;
          const mobileCard = mobileFundList ? mobileFundList.querySelector(`[data-mobile-card][data-code="${{row.dataset.code}}"]`) : null;
          if (mobileCard) mobileCard.hidden = hidden;
        }});
        updateRanks();
        updateVisibleCount();
      }}
      function closeFilter(menu) {{
        const button = menu.querySelector(".select-trigger");
        const list = menu.querySelector(".select-list");
        if (button) button.setAttribute("aria-expanded", "false");
        if (list) list.hidden = true;
      }}
      function setFilter(menu, value, label) {{
        const key = menu.dataset.filterKey;
        if (!key || !(key in filters)) return;
        filters[key] = value;
        const button = menu.querySelector(".select-trigger");
        const options = Array.from(menu.querySelectorAll(".select-option"));
        if (button) button.textContent = label;
        closeFilter(menu);
        options.forEach((option) => {{
          option.setAttribute("aria-selected", option.dataset.value === value ? "true" : "false");
        }});
        applyFilter();
      }}
      function sortByHeader(headerIndex, direction) {{
        const header = headers[headerIndex];
        if (!header) return;
        const type = header.dataset.sortType || "text";
        const columnIndex = Number(header.dataset.columnIndex);
        const rows = Array.from(tbody.querySelectorAll("tr"));
        rows.sort((a, b) => {{
          const aValue = readValue(a.children[columnIndex], type);
          const bValue = readValue(b.children[columnIndex], type);
          const result = type === "number" ? aValue - bValue : String(aValue).localeCompare(String(bValue), "zh-CN", {{ numeric: true }});
          return direction === "asc" ? result : -result;
        }});
        rows.forEach((row) => tbody.appendChild(row));
        if (mobileFundList) {{
          rows.forEach((row) => {{
            const card = mobileFundList.querySelector(`[data-mobile-card][data-code="${{row.dataset.code}}"]`);
            if (card) mobileFundList.appendChild(card);
          }});
        }}
        applyFilter();
        updateIndicators();
      }}
      filterMenus.forEach((menu) => {{
        const button = menu.querySelector(".select-trigger");
        const list = menu.querySelector(".select-list");
        const options = Array.from(menu.querySelectorAll(".select-option"));
        if (!button || !list) return;
        button.addEventListener("click", () => {{
          const expanded = button.getAttribute("aria-expanded") === "true";
          filterMenus.forEach((item) => {{
            if (item !== menu) closeFilter(item);
          }});
          button.setAttribute("aria-expanded", expanded ? "false" : "true");
          list.hidden = expanded;
        }});
        options.forEach((option) => {{
          option.addEventListener("click", () => setFilter(menu, option.dataset.value || "all", option.textContent.trim()));
        }});
      }});
      document.addEventListener("click", (event) => {{
        filterMenus.forEach((menu) => {{
          if (!menu.contains(event.target)) closeFilter(menu);
        }});
        if (columnMenu && !columnMenu.contains(event.target)) closeColumnPanel();
      }});
      if (columnToggle && columnPanel) {{
        columnToggle.addEventListener("click", () => {{
          const expanded = columnToggle.getAttribute("aria-expanded") === "true";
          filterMenus.forEach((menu) => closeFilter(menu));
          columnToggle.setAttribute("aria-expanded", expanded ? "false" : "true");
          columnPanel.hidden = expanded;
        }});
      }}
      if (columnReset) {{
        columnReset.addEventListener("click", () => {{
          visibleColumns = new Set(defaultVisibleColumns);
          saveVisibleColumns(visibleColumns);
          applyColumnVisibility();
        }});
      }}
      if (resetButton) {{
        resetButton.addEventListener("click", () => {{
          filterMenus.forEach((menu) => {{
            const firstOption = menu.querySelector('.select-option[data-value="all"]');
            if (firstOption) setFilter(menu, "all", firstOption.textContent.trim());
          }});
          activeIndex = 0;
          activeDirection = "desc";
          sortByHeader(activeIndex, activeDirection);
        }});
      }}
      document.querySelectorAll(".portfolio-table").forEach((portfolioTable) => {{
        portfolioTable.addEventListener("click", (event) => {{
          const amountCell = event.target.closest(".editable-amount");
          if (amountCell && portfolioTable.contains(amountCell)) {{
            beginAmountEdit(amountCell);
            return;
          }}
          const statusCell = event.target.closest(".editable-status");
          if (statusCell && portfolioTable.contains(statusCell)) beginStatusEdit(statusCell);
        }});
        portfolioTable.addEventListener("keydown", (event) => {{
          if (event.key !== "Enter" && event.key !== " ") return;
          const amountCell = event.target.closest(".editable-amount");
          const statusCell = event.target.closest(".editable-status");
          if (amountCell && portfolioTable.contains(amountCell)) {{
            event.preventDefault();
            beginAmountEdit(amountCell);
          }} else if (statusCell && portfolioTable.contains(statusCell)) {{
            event.preventDefault();
            beginStatusEdit(statusCell);
          }}
        }});
      }});
      headers.forEach((header, index) => {{
        const button = header.querySelector(".sort-button");
        if (!button) return;
        button.addEventListener("click", () => {{
          activeDirection = activeIndex === index && activeDirection === "asc" ? "desc" : "asc";
          activeIndex = index;
          sortByHeader(activeIndex, activeDirection);
        }});
      }});
      buildColumnOptions();
      applyColumnVisibility();
      refreshPortfolioViews();
      sortByHeader(activeIndex, activeDirection);
    }})();
  </script>
</body>
</html>
"""


def write_snapshot(
    funds: list[Fund],
    output_json: Path,
    tracking_payload: Optional[dict[str, object]] = None,
) -> None:
    cards = score_cards(funds)
    tracking_latest = latest_tracking_record(tracking_payload or {})
    payload = {
        "generated_at": now_beijing().isoformat(timespec="seconds"),
        "source_health": build_source_health(funds),
        "scoring_model": {
            "method": "return-priority model for the current A-share watchlist; return metrics carry 55%, tracking error and base fee carry 35%, fund size carries 6%, transaction frictions carry 4%; subscription status and purchase limits are execution filters only and do not affect tier scores; lower-is-better metrics are reverse normalized; fund size uses log10 before normalization",
            "tier_method": "S/A/B/C/D relative percentile buckets within the current watchlist",
            "weights": {rule["key"]: rule["weight"] for rule in SCORING_RULES},
            "rules": SCORING_RULES,
        },
        "auto_invest_plan": {
            "frequency": AUTO_INVEST_FREQUENCY,
            "next_debit_date": AUTO_INVEST_NEXT_DEBIT_DATE,
            "active_total": sum(AUTO_INVEST_AMOUNTS.values()),
            "paused_total": sum(PAUSED_AUTO_INVEST_AMOUNTS.values()),
            "active_amounts": AUTO_INVEST_AMOUNTS,
            "paused_amounts": PAUSED_AUTO_INVEST_AMOUNTS,
        },
        "holding_plan": {
            "holding_total": sum(HOLDING_AMOUNTS.values()),
            "holding_count": sum(1 for amount in HOLDING_AMOUNTS.values() if amount > 0),
            "holding_amounts": HOLDING_AMOUNTS,
            "active_without_holding": sorted(set(AUTO_INVEST_AMOUNTS) - set(HOLDING_AMOUNTS)),
            "holding_but_paused": sorted(set(HOLDING_AMOUNTS) & set(PAUSED_AUTO_INVEST_AMOUNTS)),
        },
        "tracking_plan": {
            "schema_version": TRACKING_SCHEMA_VERSION,
            "file": TRACKING_FILENAME,
            "record_count": len(tracking_records(tracking_payload or {})),
            "latest_date": tracking_latest.get("date") or tracking_latest.get("recorded_at"),
            "refresh_policy": "GitHub Actions refreshes the main data three times per Beijing day; portfolio_tracking.json upserts today's record and appends only when the Beijing date changes.",
            "refresh_times_beijing": list(AUTO_REFRESH_TIMES_BEIJING),
            "note": "Long-term holding and return records are stored in portfolio_tracking.json; generated HTML reads the saved records but does not invent market value or profit.",
        },
        "funds": [
            {
                "code": f.code,
                "name": f.name,
                "status": fund_status(f.code),
                "holding_amount": HOLDING_AMOUNTS.get(f.code, 0),
                "auto_invest_amount": AUTO_INVEST_AMOUNTS.get(f.code, 0),
                "paused_auto_invest_amount": PAUSED_AUTO_INVEST_AMOUNTS.get(f.code, 0),
                "holding_horizon": "long",
                "holding_horizon_text": "长期持有",
                "investing_tier": cards[f.code]["tier"],
                "investing_score": cards[f.code]["score"],
                "investing_rank": cards[f.code]["rank"],
                "subscription_status": f.subscription_status,
                "subscription_status_raw": f.subscription_status_raw,
                "fund_size_billion": f.fund_size_billion,
                "daily_limit": f.daily_limit,
                "agency_limit_label": f.agency_limit_label,
                "direct_limit": f.direct_limit,
                "buy_rate": f.buy_rate,
                "management_fee": f.management_fee,
                "custody_fee": f.custody_fee,
                "sales_fee": f.sales_fee,
                "base_annual_fee_rate": f.base_annual_fee_rate,
                "operation_fee": f.operation_fee,
                "one_year": f.one_year,
                "three_year": f.three_year,
                "day_change": f.day_change,
                "tracking_index": f.tracking_index,
                "tracking_error": f.tracking_error,
                "tracking_avg_error": f.tracking_avg_error,
                "tracking_error_date": f.tracking_error_date,
                "free_after_days": f.free_after_days,
                "redemption_rules": f.redemption_rules,
                "source_notes": f.source_notes,
                "direct_limit_source": f.direct_limit_source,
            }
            for f in funds
        ],
    }
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_direct_limit_candidates(output_json: Path) -> None:
    payload = {
        "generated_at": now_beijing().isoformat(timespec="seconds"),
        "note": "Candidate limit announcements only. Use Codex/web/PDF reading to extract current direct-sale limits into direct_limits.json.",
        "funds": {},
    }
    for code in FUND_CODES:
        try:
            candidates = fetch_direct_limit_announcements(code)
            for candidate in candidates[:3]:
                try:
                    candidate.update(fetch_announcement_content(candidate.get("id", "")))
                    time.sleep(0.2)
                except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                    candidate["content_error"] = exc.__class__.__name__
            payload["funds"][code] = candidates
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            payload["funds"][code] = [{"error": exc.__class__.__name__}]
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_direct_limit_overrides(path: Path) -> dict[str, dict]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must be a JSON object keyed by fund code.")
    normalized: dict[str, dict] = {}
    for code, item in payload.items():
        if isinstance(item, dict):
            normalized[str(code)] = item
        else:
            normalized[str(code)] = {"limit": item, "source_note": "Codex/联网查询校准"}
    return normalized


def run() -> int:
    parser = argparse.ArgumentParser(description="Generate a sortable Nasdaq QDII fund fee/limit HTML table.")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for 纳指基金支付宝对比表.html and nasdaq_fund_snapshot.json.",
    )
    parser.add_argument(
        "--direct-limits-json",
        default="",
        help="Optional JSON file with direct-sale limits keyed by fund code.",
    )
    parser.add_argument(
        "--write-direct-limit-candidates",
        action="store_true",
        help="Only write recent candidate limit-announcement URLs for Codex/PDF extraction.",
    )
    args = parser.parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_html = output_dir / "纳指基金支付宝对比表.html"
    output_json = output_dir / "nasdaq_fund_snapshot.json"
    tracking_json = output_dir / TRACKING_FILENAME
    candidate_json = output_dir / "direct_limit_candidates.json"
    direct_limit_overrides: dict[str, dict] = {}

    if args.write_direct_limit_candidates:
        write_direct_limit_candidates(candidate_json)
        print(f"wrote {candidate_json}")
        return 0

    direct_limits_path = (
        Path(args.direct_limits_json).expanduser().resolve()
        if args.direct_limits_json
        else output_dir / "direct_limits.json"
    )
    if direct_limits_path.exists():
        direct_limit_overrides = load_direct_limit_overrides(direct_limits_path)
        print(f"loaded direct limits from {direct_limits_path}")
    elif args.direct_limits_json:
        raise FileNotFoundError(direct_limits_path)

    funds = []
    for code in FUND_CODES:
        print(f"fetch {code}...", flush=True)
        funds.append(fetch_fund(code, direct_limit_overrides))

    cards = score_cards(funds)
    tracking_payload = ensure_tracking_payload(tracking_json, funds, cards)
    output_html.write_text(build_html(funds, tracking_payload, tracking_json), encoding="utf-8")
    write_snapshot(funds, output_json, tracking_payload)
    print(f"wrote {output_html}")
    print(f"wrote {output_json}")
    print(f"wrote {tracking_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
