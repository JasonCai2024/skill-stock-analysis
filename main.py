import os
import sys
from pathlib import Path

# Add bundled tradingagents to path (skill is self-contained)
SKILL_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILL_ROOT))

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

ticker = sys.argv[1] if len(sys.argv) > 1 else "601127.SS"
date = sys.argv[2] if len(sys.argv) > 2 else "2026-06-06"

config = DEFAULT_CONFIG.copy()
config["checkpoint_enabled"] = False

from tradingagents.dataflows.china.market_detector import detect_market_type, MarketType
if detect_market_type(ticker) == MarketType.CHINA_A:
    config["output_language"] = "Chinese"

ta = TradingAgentsGraph(debug=True, config=config)
_, decision = ta.propagate(ticker, date)
print(decision)

