from langchain_core.messages import AIMessage

from tradingagents.agents.utils.agent_utils import (
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_income_statement,
    is_chinese_output,
)


def _call_tool(tool_obj, *args):
    """Call a LangChain tool's underlying Python function directly."""
    return tool_obj.func(*args)


def _section(title: str, body: str) -> str:
    text = (body or "").strip()
    if not text:
        text = "无可用数据" if is_chinese_output() else "NO_DATA_AVAILABLE"
    return f"## {title}\n\n{text}"


def create_fundamentals_analyst(llm):
    del llm

    def fundamentals_analyst_node(state):
        ticker = state["company_of_interest"]
        current_date = state["trade_date"]

        fundamentals = _call_tool(get_fundamentals, ticker, current_date)
        income_statement = _call_tool(get_income_statement, ticker, "quarterly", current_date)
        balance_sheet = _call_tool(get_balance_sheet, ticker, "quarterly", current_date)
        cashflow = _call_tool(get_cashflow, ticker, "quarterly", current_date)

        if is_chinese_output():
            report = "\n\n".join(
                [
                    f"# 确定性基本面数据包: {ticker}",
                    "本节内容直接由工具输出组装而成。凡未明确出现的数值或结论，均不得额外推断。",
                    _section("公司基本面", fundamentals),
                    _section("利润表", income_statement),
                    _section("资产负债表", balance_sheet),
                    _section("现金流量表", cashflow),
                ]
            )
        else:
            report = "\n\n".join(
                [
                    f"# Deterministic Fundamentals Package: {ticker}",
                    "This section is assembled directly from tool outputs. Do not infer values that are not explicitly present below.",
                    _section("Company Fundamentals", fundamentals),
                    _section("Income Statement", income_statement),
                    _section("Balance Sheet", balance_sheet),
                    _section("Cashflow", cashflow),
                ]
            )

        return {
            "messages": [AIMessage(content=report)],
            "fundamentals_report": report,
        }

    return fundamentals_analyst_node
