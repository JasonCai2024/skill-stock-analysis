"""市场类型检测 — 判断 ticker 属于哪个市场"""
from enum import Enum
from typing import Literal


class MarketType(Enum):
    CHINA_A = "china_a"      # A股 (.SH/.SZ/.BJ)
    CHINA_HK = "china_hk"    # 港股 (.HK)
    US = "us"                # 美股
    OTHER = "other"          # 其他国际市场


# A股后缀 → CHINA_A
CHINA_A_SUFFIXES = {".SH", ".SZ", ".BJ", ".SS"}

# 港股后缀 → CHINA_HK
CHINA_HK_SUFFIXES = {".HK"}

# 美股无后缀或已知后缀 → US
US_SUFFIXES = {""}

# 其他国际后缀 → OTHER
INTERNATIONAL_SUFFIXES = {
    ".NS", ".BO", ".T", ".L", ".TO", ".AX",
    ".F", ".DE", ".PA", ".MI", ".AT", ".BR",
}


def detect_market_type(symbol: str) -> MarketType:
    """
    根据 ticker 符号判断市场类型。

    Examples:
        "AAPL"         → US
        "601127.SH"    → CHINA_A
        "000001.SZ"    → CHINA_A
        "430001.BJ"    → CHINA_A
        "0700.HK"      → CHINA_HK
        "RELIANCE.BO"  → OTHER
    """
    if not symbol:
        return MarketType.US  # 默认美股

    upper = symbol.upper()
    # 提取后缀部分（最后一个 . 之后）
    if "." in upper:
        suffix = "." + upper.rsplit(".", 1)[1]
    else:
        suffix = ""

    if suffix in CHINA_A_SUFFIXES:
        return MarketType.CHINA_A
    elif suffix in CHINA_HK_SUFFIXES:
        return MarketType.CHINA_HK
    elif suffix in INTERNATIONAL_SUFFIXES:
        return MarketType.OTHER
    else:
        # 没有后缀或未知后缀 → 假定为美股
        return MarketType.US


def is_china_a_share(symbol: str) -> bool:
    """判断是否为 A股（沪深北交所）"""
    return detect_market_type(symbol) == MarketType.CHINA_A
