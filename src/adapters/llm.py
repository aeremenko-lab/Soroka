import logging
import os
from dataclasses import dataclass
from typing import Literal, Optional

import httpx

from src.core.env_store import load_env_file

logger = logging.getLogger(__name__)

Provider = Literal["openai", "gemini"]


class LLMError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class EmptyContentError(LLMError):
    pass


@dataclass(frozen=True)
class LLMConfig:
    provider: Provider
    model: str
    api_key: str

    @property
    def selector(self) -> str:
        return f"{self.provider}:{self.model}"


class LLMClient:
    OPENAI_URL = "https://api.openai.com/v1/responses"
    GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
    HTTP_RETRY_STATUSES = {429, 500, 502, 503, 504}

    def __init__(self, config: LLMConfig, timeout: float = 60.0):
        self._config = config
        self._timeout = timeout

    @property
    def selector(self) -> str:
        return self._config.selector

    async def complete(self, messages: list[dict], max_tokens: int = 1000) -> str:
        if self._config.provider == "openai":
            return await self._complete_openai(messages, max_tokens=max_tokens)
        if self._config.provider == "gemini":
            return await self._complete_gemini(messages, max_tokens=max_tokens)
        raise LLMError(f"unsupported LLM provider: {self._config.provider}")

    async def _complete_openai(self, messages: list[dict],
                               max_tokens: int) -> str:
        body = {
            "model": self._config.model,
            "input": messages,
            "max_output_tokens": max_tokens,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                self.OPENAI_URL,
                headers={"Authorization": f"Bearer {self._config.api_key}"},
                json=body,
            )
        if r.status_code in self.HTTP_RETRY_STATUSES or r.status_code != 200:
            raise LLMError(f"{r.status_code}: {r.text[:200]}",
                           status_code=r.status_code)
        text = _extract_openai_text(r.json())
        if not text:
            logger.warning("openai %s returned empty content", self._config.model)
            raise EmptyContentError(f"empty content from {self.selector}")
        return text

    async def _complete_gemini(self, messages: list[dict],
                               max_tokens: int) -> str:
        prompt = _messages_to_prompt(messages)
        model = self._config.model.removeprefix("models/")
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                f"{self.GEMINI_BASE}/models/{model}:generateContent",
                headers={"x-goog-api-key": self._config.api_key},
                json=body,
            )
        if r.status_code in self.HTTP_RETRY_STATUSES or r.status_code != 200:
            raise LLMError(f"{r.status_code}: {r.text[:200]}",
                           status_code=r.status_code)
        text = _extract_gemini_text(r.json())
        if not text:
            logger.warning("gemini %s returned empty content", self._config.model)
            raise EmptyContentError(f"empty content from {self.selector}")
        return text


def build_llm_client() -> Optional[LLMClient]:
    try:
        config = load_llm_config()
    except LLMError as e:
        logger.warning("LLM config ignored: %s", e)
        return None
    return LLMClient(config) if config else None


def load_llm_config() -> Optional[LLMConfig]:
    load_env_file(override=True)
    raw_selector = os.environ.get("SOROKA_LLM_MODEL", "").strip()
    provider = os.environ.get("SOROKA_LLM_PROVIDER", "").strip().lower()
    model = raw_selector

    if ":" in raw_selector:
        prefix, _, rest = raw_selector.partition(":")
        if prefix.lower() in ("openai", "gemini"):
            provider = prefix.lower()
            model = rest.strip()

    if not provider and not model:
        return None
    if provider not in ("openai", "gemini"):
        raise LLMError(
            "SOROKA_LLM_MODEL must look like openai:<model> or gemini:<model>"
        )
    if not model:
        raise LLMError("SOROKA_LLM_MODEL must include a model id")

    key_name = (
        "SOROKA_OPENAI_API_KEY" if provider == "openai"
        else "SOROKA_GEMINI_API_KEY"
    )
    api_key = os.environ.get(key_name, "").strip()
    if not api_key:
        return None
    return LLMConfig(provider=provider, model=model, api_key=api_key)


def describe_llm_config() -> str:
    try:
        load_env_file(override=True)
        selector = os.environ.get("SOROKA_LLM_MODEL", "").strip()
        config = load_llm_config()
    except LLMError as e:
        return f"ошибка: {e}"
    if config:
        return f"{config.selector} ✓"
    if selector:
        return f"{selector} без ключа"
    return "—"


def _messages_to_prompt(messages: list[dict]) -> str:
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(f"{role}: {content}")
        else:
            parts.append(f"{role}: {content!r}")
    return "\n\n".join(parts)


def _extract_openai_text(data: dict) -> str:
    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    chunks: list[str] = []
    for item in data.get("output", []) or []:
        for part in item.get("content", []) or []:
            if part.get("type") in ("output_text", "text") and part.get("text"):
                chunks.append(part["text"])
    return "".join(chunks).strip()


def _extract_gemini_text(data: dict) -> str:
    chunks: list[str] = []
    for cand in data.get("candidates", []) or []:
        content = cand.get("content") or {}
        for part in content.get("parts", []) or []:
            text = part.get("text")
            if text:
                chunks.append(text)
    return "".join(chunks).strip()
