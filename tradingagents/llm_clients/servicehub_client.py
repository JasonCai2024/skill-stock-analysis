"""ServiceHub LLM client — routes all LLM calls through ServiceHub's
``/api/llm/paid-rotation`` endpoint so that API keys never leave the
ServiceHub instance.

The ``provider`` field on the request is fixed to ``minimax`` (the
ServiceHub admin configures the actual backend key), and the ``model``
field is passed through as ``MiniMax-M2.7-highspeed``.
"""

import os
import time
import logging
import re
from typing import Optional, Any, List

import httpx

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TOOL_SIGNATURES = {
    "get_fundamentals": ["ticker", "curr_date"],
    "get_balance_sheet": ["ticker", "freq", "curr_date"],
    "get_cashflow": ["ticker", "freq", "curr_date"],
    "get_income_statement": ["ticker", "freq", "curr_date"],
    "get_news": ["ticker", "start_date", "end_date"],
    "get_global_news": ["curr_date", "look_back_days", "limit"],
    "get_insider_transactions": ["ticker"],
    "get_stock_data": ["symbol", "start_date", "end_date"],
    "get_indicators": ["symbol", "indicator", "curr_date", "look_back_days"],
    "get_verified_market_snapshot": ["symbol", "curr_date", "look_back_days"],
}

def parse_args_string(name: str, args_str: str, current_date_in_prompt: Optional[str] = None) -> dict:
    args_str = args_str.strip()
    if not args_str:
        return {}
    
    args = {}
    if "=" in args_str:
        try:
            import ast
            expr = f"f({args_str})"
            tree = ast.parse(expr)
            call = tree.body[0].value
            
            # Parse positional arguments based on signature order
            sig = TOOL_SIGNATURES.get(name, [])
            for idx, arg_node in enumerate(call.args):
                if idx < len(sig):
                    args[sig[idx]] = ast.literal_eval(arg_node)
            
            # Parse keyword arguments
            for kw in call.keywords:
                args[kw.arg] = ast.literal_eval(kw.value)
        except Exception:
            kv_pairs = re.findall(r'(\w+)\s*=\s*(["\'](?:\\.|[^"\'\\])*["\']|\[.*?\]|\S+)', args_str)
            for k, v in kv_pairs:
                v = v.rstrip(",")
                if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                    v = v[1:-1]
                args[k] = v
    else:
        # Positional arguments parsing
        try:
            import ast
            expr = f"[{args_str}]"
            parts = ast.literal_eval(expr)
            if not isinstance(parts, list):
                parts = [parts]
        except Exception:
            parts = []
            pattern = r',(?=(?:[^\'"]*[\'"][^\'"]*[\'"])*[^\'"]*$)'
            split_parts = re.split(pattern, args_str)
            for p in split_parts:
                p = p.strip()
                if (p.startswith('"') and p.endswith('"')) or (p.startswith("'") and p.endswith("'")):
                    p = p[1:-1]
                parts.append(p)

        sig = TOOL_SIGNATURES.get(name, [])
        for idx, part in enumerate(parts):
            if idx < len(sig):
                param_name = sig[idx]
                if param_name in ("look_back_days", "limit") and isinstance(part, str) and part.isdigit():
                    args[param_name] = int(part)
                else:
                    args[param_name] = part

    # --- Robust Parameter Normalization & Standardization ---
    sig = TOOL_SIGNATURES.get(name, [])
    
    # 1. Normalize ticker / symbol (keys and list values)
    ticker_keys = ["ticker", "tickers", "symbol", "symbols"]
    target_ticker_key = None
    if "symbol" in sig:
        target_ticker_key = "symbol"
    elif "ticker" in sig:
        target_ticker_key = "ticker"
        
    if target_ticker_key:
        found_val = None
        for k in ticker_keys:
            if k in args:
                found_val = args.pop(k)
                break
        if found_val is not None:
            if isinstance(found_val, list):
                found_val = found_val[0] if found_val else ""
            args[target_ticker_key] = str(found_val)
            
    # 2. Normalize date / curr_date / trade_date / current_date
    date_keys = ["curr_date", "current_date", "date", "trade_date"]
    if "curr_date" in sig:
        found_val = None
        for k in date_keys:
            if k in args:
                found_val = args.pop(k)
                break
        if found_val is not None:
            args["curr_date"] = str(found_val)
        elif current_date_in_prompt:
            args["curr_date"] = current_date_in_prompt

    # 3. Normalize start_date / end_date defaults
    if "start_date" in sig and "start_date" not in args and current_date_in_prompt:
        try:
            from datetime import datetime, timedelta
            dt = datetime.strptime(current_date_in_prompt, "%Y-%m-%d")
            args["start_date"] = (dt - timedelta(days=30)).strftime("%Y-%m-%d")
        except Exception:
            pass
            
    if "end_date" in sig and "end_date" not in args and current_date_in_prompt:
        args["end_date"] = current_date_in_prompt

    # 4. Normalize indicator / indicators (and convert lists to comma-separated string)
    if "indicator" in sig:
        found_val = None
        for k in ["indicator", "indicators"]:
            if k in args:
                found_val = args.pop(k)
                break
        if found_val is not None:
            if isinstance(found_val, list):
                found_val = ",".join(str(item) for item in found_val)
            args["indicator"] = str(found_val)
            
    # 5. Clean up other keys not in signature to prevent validation errors
    if sig:
        for k in list(args.keys()):
            if k not in sig:
                args.pop(k)
                
    # 6. Ensure default integer types for known fields
    for k in ["look_back_days", "limit"]:
        if k in args and args[k] is not None:
            try:
                args[k] = int(args[k])
            except ValueError:
                pass

    return args

def parse_text_tool_calls(text: str, current_date_in_prompt: Optional[str] = None) -> list:
    pattern = r'(\bget_[a-z_]+)\((.*?)\)'
    matches = re.finditer(pattern, text)
    tool_calls = []
    for match in matches:
        name = match.group(1)
        args_str = match.group(2)
        # Only parse if it's a known tool name
        if name in TOOL_SIGNATURES:
            args = parse_args_string(name, args_str, current_date_in_prompt)
            tool_calls.append({
                "name": name,
                "args": args,
                "id": f"call_{name}_{len(tool_calls)}"
            })
    return tool_calls

def _resolve_env(key: str, default: Optional[str] = None) -> Optional[str]:
    return os.environ.get(key, default)


def _extract_prompt_content(messages: List[BaseMessage]) -> str:
    """Flatten a list of LangChain messages into a single string prompt."""
    parts = []
    for msg in messages:
        content = getattr(msg, "content", "") or ""
        if isinstance(msg, SystemMessage):
            parts.append(f"[system] {content}")
        elif isinstance(msg, HumanMessage):
            parts.append(f"[user] {content}")
        elif isinstance(msg, AIMessage):
            parts.append(f"[assistant] {content}")
        elif isinstance(msg, ToolMessage) or getattr(msg, "type", None) == "tool":
            name = getattr(msg, "name", "") or "tool"
            parts.append(f"[user] [Tool Output: {name}]\n{content}")
        else:
            parts.append(str(content))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# ChatModel wrapper
# ---------------------------------------------------------------------------

class ServiceHubChatModel(BaseChatModel):
    """LangChain BaseChatModel that calls the ServiceHub LLM gateway.

    Each call is a single HTTP POST — no session, no history accumulation —
    matching the single-turn invoke() pattern used by TradingAgents nodes.

    ``bind_tools`` is implemented as a no-op because ServiceHub does not
    support function-calling tools. The LLM receives tool descriptions in
    the prompt text and may mention tool names in its response; the caller
    is responsible for handling that gracefully.

    Environment variables required
    ------------------------------
    SERVICETUBER_BASE_URL  : ServiceHub root, e.g. ``https://www.ccailab.top``
                            (falls back to ``http://127.0.0.1:8000`` for local dev)
    SERVICETUBER_USERNAME  : ServiceHub account username
    SERVICETUBER_PASSTOKEN : ServiceHub account passtoken
    SERVICETUBER_TIMEOUT   : optional, request timeout in seconds (default 180)
    """

    model: str = "MiniMax-M2.7-highspeed"
    provider: str = "minimax"

    @property
    def _llm_type(self) -> str:
        """Identifier used by LangChain for logging and caching."""
        return "servicehub_chat"

    @property
    def _identifying_params(self) -> dict:
        return {"model": self.model, "provider": self.provider}

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        **kwargs,
    ) -> ChatResult:
        """Called by LangChain's invoke() / batch() machinery."""
        base_url = _resolve_env(
            "SERVICETUBER_BASE_URL",
            "http://127.0.0.1:8000",
        ).rstrip("/")
        if base_url.endswith("/api"):
            base_url = base_url[:-4]

        url = f"{base_url}/api/llm/paid-rotation"
        username = _resolve_env("SERVICETUBER_USERNAME")
        passtoken = _resolve_env("SERVICETUBER_PASSTOKEN")
        timeout = float(_resolve_env("SERVICETUBER_TIMEOUT") or "180")

        if not username or not passtoken:
            raise ValueError(
                "SERVICETUBER_USERNAME and SERVICETUBER_PASSTOKEN must be set "
                "in the environment before calling the ServiceHub LLM client."
            )

        prompt_text = _extract_prompt_content(messages)

        # Split system / user if the prompt uses [system] marker
        system_prompt: Optional[str] = None
        if prompt_text.startswith("[system]") and "\n[user]" in prompt_text:
            idx = prompt_text.index("\n[user]")
            system_prompt = prompt_text[len("[system]"):idx].strip()
            user_prompt = prompt_text[idx + len("\n[user]"):].strip()
        else:
            user_prompt = prompt_text

        payload = {
            "username": username,
            "passtoken": passtoken,
            "user_prompt": user_prompt,
            "system_prompt": system_prompt or "",
            "task_type": "text_arrange",
            "provider": self.provider,
            "model": self.model,
        }

        logger.debug("ServiceHub LLM request → %s", url)
        t0 = time.time()

        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                "ServiceHub LLM HTTP error %s: %s",
                e.response.status_code,
                e.response.text,
            )
            raise
        except Exception as e:
            logger.error("ServiceHub LLM request failed: %s", e)
            raise

        elapsed = time.time() - t0
        logger.debug("ServiceHub LLM response ← %.2fs", elapsed)

        code = data.get("code")
        if code != 200:
            raise RuntimeError(
                f"ServiceHub LLM returned code={code}: {data.get('message', data)}"
            )

        result = data.get("data", {})
        content = result.get("processed_text", "")

        # Identify successfully executed tools from history to prevent infinite loops
        # while allowing retries (on validation error) and sequential tool calls.
        successful_tools = set()
        if messages:
            for msg in messages:
                if isinstance(msg, ToolMessage) or getattr(msg, "type", None) == "tool":
                    tool_name = getattr(msg, "name", "")
                    tool_content = getattr(msg, "content", "") or ""
                    # A tool run is considered successful if its content doesn't indicate a validation/invocation error
                    if tool_name and not ("ValidationError" in tool_content or tool_content.startswith("Error:")):
                        successful_tools.add(tool_name)

        # Extract current date from the prompt/messages to use as default value
        current_date_in_prompt = None
        if messages:
            for msg in messages:
                if isinstance(msg, SystemMessage) or getattr(msg, "type", None) == "system":
                    content_str = getattr(msg, "content", "") or ""
                    match = re.search(r"current date is (\d{4}-\d{2}-\d{2})", content_str)
                    if match:
                        current_date_in_prompt = match.group(1)
                        break

        tool_calls = []
        parsed_calls = parse_text_tool_calls(content, current_date_in_prompt)
        for call in parsed_calls:
            if call["name"] not in successful_tools:
                tool_calls.append(call)

        message = AIMessage(content=content, tool_calls=tool_calls)
        gen = ChatGeneration(message=message)
        return ChatResult(generations=[gen])

    def bind_tools(self, tools: Any, **kwargs) -> "ServiceHubChatModel":
        """No-op: ServiceHub does not support function-calling tools.

        The LLM receives tool descriptions in the prompt text. Callers that
        need structured output should use ``with_structured_output`` on a
        wrapper that retries with free-text on failure.
        """
        return self


# ---------------------------------------------------------------------------
# TradingAgents BaseLLMClient adapter
# ---------------------------------------------------------------------------

from tradingagents.llm_clients.base_client import BaseLLMClient


class ServiceHubClient(BaseLLMClient):
    """TradingAgents-compatible client that wraps ServiceHubChatModel."""

    def __init__(self, model: str, base_url: Optional[str] = None, **kwargs):
        super().__init__(model, base_url, **kwargs)
        self.provider = "servicehub"
        if base_url:
            os.environ["SERVICETUBER_BASE_URL"] = base_url

    def get_llm(self):
        self.warn_if_unknown_model()
        return ServiceHubChatModel(model=self.model, provider=self.provider)

    def validate_model(self) -> bool:
        # ServiceHub routes to MiniMax-M2.7-highspeed; no per-model validation needed.
        return True
