"""China A-share data package"""
from .market_detector import detect_market_type, is_china_a_share, MarketType

__all__ = ["detect_market_type", "is_china_a_share", "MarketType"]
