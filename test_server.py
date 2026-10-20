"""Unit tests for the GNews MCP server; no live API calls are made."""

import pytest

import main


@pytest.mark.asyncio
async def test_mcp_capabilities_are_registered() -> None:
    tools = {tool.name for tool in await main.mcp.list_tools()}
    resources = {str(resource.uri) for resource in await main.mcp.list_resources()}
    prompts = {prompt.name for prompt in await main.mcp.list_prompts()}

    assert tools == {"search_news", "get_top_headlines"}
    assert resources == {
        "gnews://supported-languages",
        "gnews://supported-countries",
        "gnews://query-syntax",
    }
    assert prompts == {"create_news_search_prompt"}


@pytest.mark.asyncio
async def test_search_builds_safe_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def fake_request(endpoint: str, params: dict) -> dict:
        captured.update({"endpoint": endpoint, "params": params.copy()})
        return {"totalArticles": 1, "articles": [{"title": "Example"}]}

    monkeypatch.setattr(main, "make_gnews_request", fake_request)
    result = await main.search_news(q=" AI ", lang="en", max_articles=5)

    assert result["success"] is True
    assert result["query"] == "AI"
    assert captured["endpoint"] == "search"
    assert captured["params"]["max"] == 5
    assert "apikey" not in captured["params"]
    assert "apikey" not in result["parameters_used"]


@pytest.mark.asyncio
async def test_headlines_returns_safe_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def failed_request(endpoint: str, params: dict) -> dict:
        raise main.GNewsError("GNews request timed out")

    monkeypatch.setattr(main, "make_gnews_request", failed_request)
    result = await main.get_top_headlines(category="technology")

    assert result["success"] is False
    assert result["error"] == "GNews request timed out"
    assert "apikey" not in result["parameters_used"]


@pytest.mark.asyncio
async def test_invalid_inputs_are_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported language"):
        await main.search_news(q="AI", lang="invalid")
    with pytest.raises(ValueError, match="timezone"):
        await main.search_news(q="AI", date_from="2026-01-01T00:00:00")
    with pytest.raises(ValueError, match="date_from"):
        await main.search_news(
            q="AI",
            date_from="2026-02-01T00:00:00Z",
            date_to="2026-01-01T00:00:00Z",
        )


def test_get_api_key_rejects_missing_and_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GNEWS_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GNEWS_API_KEY"):
        main.get_api_key()

    monkeypatch.setenv("GNEWS_API_KEY", "your_gnews_api_key_here")
    with pytest.raises(ValueError, match="GNEWS_API_KEY"):
        main.get_api_key()


def test_get_api_key_strips_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GNEWS_API_KEY", "  secret-value  ")
    assert main.get_api_key() == "secret-value"
