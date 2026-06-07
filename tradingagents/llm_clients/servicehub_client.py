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
from typing import Optional, Any, List

import httpx

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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

        gen = ChatGeneration(message=AIMessage(content=content))
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
