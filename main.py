"""Production-ready MCP server for the GNews API."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import Field


# Load the repository's .env file for local development. Existing process
# environment variables win, which is the expected behavior in production.
load_dotenv(dotenv_path=Path(__file__).with_name(".env"), override=False)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

GNEWS_BASE_URL = os.getenv("GNEWS_BASE_URL", "https://gnews.io/api/v4").rstrip("/")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("GNEWS_TIMEOUT_SECONDS", "15"))

mcp = FastMCP(
    name="gnews-server",
    instructions=(
        "Search GNews articles and retrieve top headlines. Use ISO 8601 UTC "
        "timestamps for date filters."
    ),
)

SUPPORTED_LANGUAGES = {
    "ar": "Arabic", "zh": "Chinese", "nl": "Dutch", "en": "English",
    "fr": "French", "de": "German", "el": "Greek", "hi": "Hindi",
    "it": "Italian", "ja": "Japanese", "ml": "Malayalam", "mr": "Marathi",
    "no": "Norwegian", "pt": "Portuguese", "ro": "Romanian", "ru": "Russian",
    "es": "Spanish", "sv": "Swedish", "ta": "Tamil", "te": "Telugu",
    "uk": "Ukrainian",
}

SUPPORTED_COUNTRIES = {
    "au": "Australia", "br": "Brazil", "ca": "Canada", "cn": "China",
    "eg": "Egypt", "fr": "France", "de": "Germany", "gr": "Greece",
    "hk": "Hong Kong", "in": "India", "ie": "Ireland", "it": "Italy",
    "jp": "Japan", "nl": "Netherlands", "no": "Norway", "pk": "Pakistan",
    "pe": "Peru", "ph": "Philippines", "pt": "Portugal", "ro": "Romania",
    "ru": "Russian Federation", "sg": "Singapore", "es": "Spain",
    "se": "Sweden", "ch": "Switzerland", "tw": "Taiwan", "ua": "Ukraine",
    "gb": "United Kingdom", "us": "United States",
}

CATEGORIES = {
    "general", "world", "nation", "business", "technology",
    "entertainment", "sports", "science", "health",
}
SEARCH_FIELDS = {"title", "description", "content"}
NULLABLE_FIELDS = {"description", "content", "image"}


class GNewsError(RuntimeError):
    """A safe, user-facing GNews request error."""


def get_api_key() -> str:
    """Return the configured API key without exposing it in logs or responses."""
    api_key = os.getenv("GNEWS_API_KEY", "").strip()
    if not api_key or api_key == "your_gnews_api_key_here":
        raise ValueError(
            "GNEWS_API_KEY is required. Set it in .env or in the process environment. "
            "Get a key from https://gnews.io/."
        )
    return api_key


def _validate_csv(value: str | None, allowed: set[str], parameter: str) -> None:
    if value is None:
        return
    supplied = {item.strip() for item in value.split(",") if item.strip()}
    invalid = supplied - allowed
    if not supplied or invalid:
        raise ValueError(
            f"Invalid {parameter}: {', '.join(sorted(invalid)) or value}. "
            f"Allowed values: {', '.join(sorted(allowed))}"
        )


def _parse_date(value: str | None, parameter: str) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{parameter} must be a valid ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{parameter} must include a timezone, for example ...Z")
    return parsed


def _validate_common(
    *, lang: str | None, country: str | None, max_articles: int, page: int,
    nullable: str | None, date_from: str | None, date_to: str | None,
) -> None:
    if lang is not None and lang not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language '{lang}'")
    if country is not None and country not in SUPPORTED_COUNTRIES:
        raise ValueError(f"Unsupported country '{country}'")
    if not 1 <= max_articles <= 100:
        raise ValueError("max_articles must be between 1 and 100")
    if page < 1:
        raise ValueError("page must be 1 or greater")
    _validate_csv(nullable, NULLABLE_FIELDS, "nullable")
    start = _parse_date(date_from, "date_from")
    end = _parse_date(date_to, "date_to")
    if start and end and start > end:
        raise ValueError("date_from must be before or equal to date_to")


async def make_gnews_request(endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    """Call GNews with bounded timeouts and secret-safe error handling."""
    request_params = {**params, "apikey": get_api_key()}
    timeout = httpx.Timeout(REQUEST_TIMEOUT_SECONDS, connect=min(5.0, REQUEST_TIMEOUT_SECONDS))

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            logger.info("Requesting GNews endpoint=%s", endpoint)
            response = await client.get(f"{GNEWS_BASE_URL}/{endpoint}", params=request_params)
    except httpx.TimeoutException as exc:
        raise GNewsError("GNews request timed out") from exc
    except httpx.RequestError as exc:
        raise GNewsError("Could not connect to GNews") from exc

    if response.is_error:
        detail = ""
        try:
            payload = response.json()
            errors = payload.get("errors") if isinstance(payload, dict) else None
            if errors:
                detail = f": {errors}"
        except ValueError:
            pass
        logger.warning("GNews returned HTTP %s", response.status_code)
        raise GNewsError(f"GNews returned HTTP {response.status_code}{detail}")

    try:
        data = response.json()
    except ValueError as exc:
        raise GNewsError("GNews returned an invalid JSON response") from exc
    if not isinstance(data, dict):
        raise GNewsError("GNews returned an unexpected response")

    logger.info("GNews returned %s articles", data.get("totalArticles", 0))
    return data


@mcp.tool()
async def search_news(
    q: Annotated[str, Field(description="Search keywords; supports AND, OR, NOT, and quoted phrases.")],
    lang: Annotated[str | None, Field(description="Two-letter language code.")] = None,
    country: Annotated[str | None, Field(description="Two-letter country code.")] = None,
    max_articles: Annotated[int, Field(description="Number of articles (1-100).")] = 10,
    search_in: Annotated[
        str | None, Field(description="Comma-separated: title, description, content.")
    ] = None,
    nullable: Annotated[
        str | None, Field(description="Comma-separated: description, content, image.")
    ] = None,
    date_from: Annotated[str | None, Field(description="ISO 8601 start timestamp.")] = None,
    date_to: Annotated[str | None, Field(description="ISO 8601 end timestamp.")] = None,
    sortby: Literal["publishedAt", "relevance"] = "publishedAt",
    page: Annotated[int, Field(description="Page number, starting at 1.")] = 1,
) -> dict[str, Any]:
    """Search for news articles using keywords and optional filters."""
    if not q.strip():
        raise ValueError("q must not be empty")
    _validate_common(
        lang=lang, country=country, max_articles=max_articles, page=page,
        nullable=nullable, date_from=date_from, date_to=date_to,
    )
    _validate_csv(search_in, SEARCH_FIELDS, "search_in")

    params: dict[str, Any] = {"q": q.strip(), "max": max_articles, "sortby": sortby, "page": page}
    optional = {
        "lang": lang, "country": country, "in": search_in, "nullable": nullable,
        "from": date_from, "to": date_to,
    }
    params.update({key: value for key, value in optional.items() if value is not None})

    try:
        result = await make_gnews_request("search", params)
        return {
            "success": True, "query": q.strip(),
            "totalArticles": result.get("totalArticles", 0),
            "articles": result.get("articles", []), "parameters_used": params,
        }
    except (GNewsError, ValueError) as exc:
        return {"success": False, "error": str(exc), "query": q.strip(), "parameters_used": params}


@mcp.tool()
async def get_top_headlines(
    category: Literal[
        "general", "world", "nation", "business", "technology",
        "entertainment", "sports", "science", "health",
    ] = "general",
    lang: Annotated[str | None, Field(description="Two-letter language code.")] = None,
    country: Annotated[str | None, Field(description="Two-letter country code.")] = None,
    max_articles: Annotated[int, Field(description="Number of articles (1-100).")] = 10,
    nullable: Annotated[
        str | None, Field(description="Comma-separated: description, content, image.")
    ] = None,
    date_from: Annotated[str | None, Field(description="ISO 8601 start timestamp.")] = None,
    date_to: Annotated[str | None, Field(description="ISO 8601 end timestamp.")] = None,
    q: Annotated[str | None, Field(description="Additional keywords.")] = None,
    page: Annotated[int, Field(description="Page number, starting at 1.")] = 1,
) -> dict[str, Any]:
    """Get current top headlines for a category."""
    _validate_common(
        lang=lang, country=country, max_articles=max_articles, page=page,
        nullable=nullable, date_from=date_from, date_to=date_to,
    )
    if category not in CATEGORIES:
        raise ValueError(f"Unsupported category '{category}'")

    params: dict[str, Any] = {"category": category, "max": max_articles, "page": page}
    optional = {
        "lang": lang, "country": country, "nullable": nullable,
        "from": date_from, "to": date_to, "q": q.strip() if q else None,
    }
    params.update({key: value for key, value in optional.items() if value is not None})

    try:
        result = await make_gnews_request("top-headlines", params)
        return {
            "success": True, "category": category,
            "totalArticles": result.get("totalArticles", 0),
            "articles": result.get("articles", []), "parameters_used": params,
        }
    except (GNewsError, ValueError) as exc:
        return {"success": False, "error": str(exc), "category": category, "parameters_used": params}


@mcp.resource("gnews://supported-languages")
def supported_languages() -> str:
    """List supported GNews language codes."""
    return "\n".join(f"{code}: {name}" for code, name in sorted(SUPPORTED_LANGUAGES.items()))


@mcp.resource("gnews://supported-countries")
def supported_countries() -> str:
    """List supported GNews country codes."""
    return "\n".join(f"{code}: {name}" for code, name in sorted(SUPPORTED_COUNTRIES.items()))


@mcp.resource("gnews://query-syntax")
def query_syntax() -> str:
    """Describe the supported search query syntax."""
    return (
        "Use AND, OR, and NOT to combine terms. Use double quotes for exact phrases "
        "and parentheses for grouping. Example: (Tesla OR \"electric vehicle\") NOT stock."
    )


@mcp.prompt()
def create_news_search_prompt(topic: str, days_back: int = 7) -> str:
    """Create a concise prompt for researching recent news about a topic."""
    if not topic.strip():
        raise ValueError("topic must not be empty")
    if not 1 <= days_back <= 365:
        raise ValueError("days_back must be between 1 and 365")
    start = datetime.now(timezone.utc) - timedelta(days=days_back)
    return (
        f"Research news about {topic.strip()} published since {start.isoformat()}. "
        "Use search_news, compare multiple sources, identify major developments, "
        "and include source URLs and publication dates."
    )


def main() -> None:
    """Validate configuration and run the stdio MCP server."""
    try:
        get_api_key()
    except ValueError as exc:
        logger.error("Configuration error: %s", exc)
        raise SystemExit(2) from exc

    logger.info("Starting GNews MCP server using stdio transport")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
