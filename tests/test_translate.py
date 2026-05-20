import pytest
from unittest.mock import AsyncMock

from src.core.translate import is_russian, summarize_ru


# ---------- is_russian ----------

def test_is_russian_true_for_cyrillic_text():
    assert is_russian("Привет, это русский текст про нейросети.") is True


def test_is_russian_false_for_english_text():
    assert is_russian("Hello, this is an English article about LLMs.") is False


def test_is_russian_false_for_empty_string():
    assert is_russian("") is False


def test_is_russian_false_for_symbols_only():
    assert is_russian("123 !@# ... ---") is False


def test_is_russian_true_when_russian_with_english_brand_names():
    text = (
        "В этой статье мы рассмотрим OpenAI и Anthropic, "
        "сравнивая их подходы к разработке LLM моделей."
    )
    assert is_russian(text) is True


def test_is_russian_false_when_english_with_a_few_russian_words():
    text = (
        "This is a long English article about software engineering "
        "and modern development practices, occasionally mentioning "
        "слово but mostly written in plain English prose for readers."
    )
    assert is_russian(text) is False


# ---------- summarize_ru ----------

@pytest.mark.asyncio
async def test_summarize_ru_returns_none_when_llm_is_none():
    out = await summarize_ru(None, text="hello world")
    assert out is None


@pytest.mark.asyncio
async def test_summarize_ru_returns_none_for_empty_text():
    fake = AsyncMock()
    fake.complete = AsyncMock(return_value="ok")
    out = await summarize_ru(fake, text="   ")
    assert out is None
    fake.complete.assert_not_called()


@pytest.mark.asyncio
async def test_summarize_ru_returns_cleaned_text_on_success():
    fake = AsyncMock()
    fake.complete = AsyncMock(return_value="  Краткое описание статьи о нейросетях.  ")
    out = await summarize_ru(fake, text="some english article body")
    assert out == "Краткое описание статьи о нейросетях."


@pytest.mark.asyncio
async def test_summarize_ru_passes_messages_and_token_budget_to_llm():
    fake = AsyncMock()
    fake.complete = AsyncMock(return_value="ok")
    await summarize_ru(fake, text="body")
    kwargs = fake.complete.call_args.kwargs
    assert kwargs["max_tokens"] == 120
    assert kwargs["messages"][0]["role"] == "user"
    assert "body" in kwargs["messages"][0]["content"]


@pytest.mark.asyncio
async def test_summarize_ru_strips_matched_quotes():
    fake = AsyncMock()
    fake.complete = AsyncMock(return_value='"Описание в кавычках"')
    out = await summarize_ru(fake, text="body")
    assert out == "Описание в кавычках"


@pytest.mark.asyncio
async def test_summarize_ru_strips_russian_guillemets():
    """«» are asymmetric — equality check on first/last char misses them.
    The guillemet branch handles them explicitly."""
    fake = AsyncMock()
    fake.complete = AsyncMock(return_value="«Описание в ёлочках»")
    out = await summarize_ru(fake, text="body")
    assert out == "Описание в ёлочках"


@pytest.mark.asyncio
async def test_summarize_ru_truncates_overlong_responses():
    fake = AsyncMock()
    fake.complete = AsyncMock(return_value="A" * 500)
    out = await summarize_ru(fake, text="body", max_chars=200)
    assert out is not None
    assert len(out) <= 200  # ellipsis included in the cap
    assert out.endswith("…")


@pytest.mark.asyncio
async def test_summarize_ru_returns_none_on_llm_exception():
    fake = AsyncMock()
    fake.complete = AsyncMock(side_effect=Exception("LLM down"))
    out = await summarize_ru(fake, text="body")
    assert out is None


@pytest.mark.asyncio
async def test_summarize_ru_returns_none_on_blank_llm_response():
    fake = AsyncMock()
    fake.complete = AsyncMock(return_value="   ")
    out = await summarize_ru(fake, text="body")
    assert out is None
