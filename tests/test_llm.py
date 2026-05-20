import json

import pytest

from src.adapters.llm import (
    EmptyContentError,
    LLMClient,
    LLMConfig,
    LLMError,
    describe_llm_config,
    load_llm_config,
)


def test_load_llm_config_from_prefixed_openai_selector(monkeypatch):
    monkeypatch.setenv("SOROKA_LLM_MODEL", "openai:gpt-test")
    monkeypatch.setenv("SOROKA_OPENAI_API_KEY", "sk-test")

    cfg = load_llm_config()

    assert cfg == LLMConfig(
        provider="openai",
        model="gpt-test",
        api_key="sk-test",
    )


def test_load_llm_config_from_gemini_selector(monkeypatch):
    monkeypatch.setenv("SOROKA_LLM_MODEL", "gemini:gemini-test")
    monkeypatch.setenv("SOROKA_GEMINI_API_KEY", "gm-test")

    cfg = load_llm_config()

    assert cfg == LLMConfig(
        provider="gemini",
        model="gemini-test",
        api_key="gm-test",
    )


def test_load_llm_config_supports_separate_provider(monkeypatch):
    monkeypatch.setenv("SOROKA_LLM_PROVIDER", "openai")
    monkeypatch.setenv("SOROKA_LLM_MODEL", "gpt-test")
    monkeypatch.setenv("SOROKA_OPENAI_API_KEY", "sk-test")

    cfg = load_llm_config()

    assert cfg is not None
    assert cfg.selector == "openai:gpt-test"


def test_load_llm_config_returns_none_when_key_missing(monkeypatch):
    monkeypatch.setenv("SOROKA_LLM_MODEL", "openai:gpt-test")

    assert load_llm_config() is None
    assert describe_llm_config() == "openai:gpt-test без ключа"


def test_load_llm_config_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("SOROKA_LLM_MODEL", "anthropic:claude")

    with pytest.raises(LLMError, match="openai:<model> or gemini:<model>"):
        load_llm_config()


@pytest.mark.asyncio
async def test_openai_complete_uses_responses_api(httpx_mock):
    httpx_mock.add_response(
        url=LLMClient.OPENAI_URL,
        method="POST",
        json={"output_text": "hello from openai"},
    )
    client = LLMClient(LLMConfig("openai", "gpt-test", "sk-test"))

    out = await client.complete(
        [{"role": "user", "content": "hello"}],
        max_tokens=50,
    )

    assert out == "hello from openai"
    request = httpx_mock.get_request()
    assert request.headers["Authorization"] == "Bearer sk-test"
    body = json.loads(request.content.decode())
    assert body["model"] == "gpt-test"
    assert body["max_output_tokens"] == 50


@pytest.mark.asyncio
async def test_openai_complete_extracts_nested_output_text(httpx_mock):
    httpx_mock.add_response(
        url=LLMClient.OPENAI_URL,
        method="POST",
        json={"output": [{
            "content": [
                {"type": "output_text", "text": "hello "},
                {"type": "text", "text": "again"},
            ],
        }]},
    )
    client = LLMClient(LLMConfig("openai", "gpt-test", "sk-test"))

    assert await client.complete([{"role": "user", "content": "x"}]) == "hello again"


@pytest.mark.asyncio
async def test_gemini_complete_uses_generate_content(httpx_mock):
    httpx_mock.add_response(
        url=f"{LLMClient.GEMINI_BASE}/models/gemini-test:generateContent",
        method="POST",
        json={"candidates": [{
            "content": {"parts": [{"text": "hello from gemini"}]},
        }]},
    )
    client = LLMClient(LLMConfig("gemini", "models/gemini-test", "gm-test"))

    out = await client.complete(
        [{"role": "user", "content": "hello"}],
        max_tokens=60,
    )

    assert out == "hello from gemini"
    request = httpx_mock.get_request()
    assert request.headers["x-goog-api-key"] == "gm-test"
    body = json.loads(request.content.decode())
    assert body["generationConfig"]["maxOutputTokens"] == 60
    assert "user: hello" in body["contents"][0]["parts"][0]["text"]


@pytest.mark.asyncio
async def test_complete_raises_on_empty_content(httpx_mock):
    httpx_mock.add_response(
        url=LLMClient.OPENAI_URL,
        method="POST",
        json={"output_text": "   "},
    )
    client = LLMClient(LLMConfig("openai", "gpt-test", "sk-test"))

    with pytest.raises(EmptyContentError):
        await client.complete([{"role": "user", "content": "x"}])
