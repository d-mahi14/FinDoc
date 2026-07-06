"""
News API client for fetching recent financial news about companies.
Uses NewsAPI.org's 'everything' endpoint with company-specific queries.
3-tier defense: SQLite cache → live API → sample data fallback.
"""

import json
import os
from datetime import datetime, timedelta
from typing import Any

import httpx

from app.models.schemas import NewsArticle
from app.utils.db import cache_get, cache_set


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
NEWS_API_BASE = "https://newsapi.org/v2/everything"

SAMPLE_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "samples"
)

# Company name mapping for search queries
COMPANY_NAMES = {
    "TCS": "Tata Consultancy Services",
    "RELIANCE": "Reliance Industries",
    "INFY": "Infosys",
    "HDFCBANK": "HDFC Bank",
    "WIPRO": "Wipro",
    "ICICIBANK": "ICICI Bank",
    "ITC": "ITC Limited",
    "SBIN": "State Bank of India",
    "BAJFINANCE": "Bajaj Finance",
    "LT": "Larsen & Toubro",
}


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------

async def fetch_news(symbol: str, days: int = 30) -> list[NewsArticle]:
    """
    Fetch recent news articles for a company.
    3-tier defense: cache → live API → sample data.

    Returns a list of NewsArticle objects — never raises on failure.
    """
    symbol = symbol.upper().strip()
    print(f"[News] Fetching news for {symbol} (last {days} days)...")

    # Tier 1: SQLite cache
    cached = await cache_get("cached_news", symbol)
    if cached:
        print(f"[News] Cache hit for {symbol}: {len(cached)} articles")
        return [NewsArticle.model_validate(a) for a in cached]

    # Tier 2: Live API
    if NEWS_API_KEY:
        try:
            articles = await _fetch_newsapi(symbol, days)
            if articles:
                await cache_set(
                    "cached_news", symbol,
                    [a.model_dump() for a in articles],
                    ttl_hours=12, source="newsapi"
                )
                print(f"[News] Live news fetched for {symbol}: {len(articles)} articles")
                return articles
        except Exception as e:
            print(f"[News] Live fetch failed for {symbol}: {e}")
    else:
        print(f"[News] No NEWS_API_KEY configured, skipping live fetch")

    # Tier 3: Sample data fallback
    sample_articles = _load_sample_news(symbol)
    if sample_articles:
        await cache_set(
            "cached_news", symbol,
            [a.model_dump() for a in sample_articles],
            ttl_hours=168, source="sample"
        )
        print(f"[News] Using sample news for {symbol}: {len(sample_articles)}")
        return sample_articles

    print(f"[News] No news data available for {symbol}")
    return []


# ---------------------------------------------------------------------------
# Live API Fetcher
# ---------------------------------------------------------------------------

async def _fetch_newsapi(symbol: str, days: int = 30) -> list[NewsArticle]:
    """Fetch news from NewsAPI.org."""
    company_name = COMPANY_NAMES.get(symbol, symbol)
    from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    params = {
        "q": f'"{company_name}" AND (financial OR quarterly OR results OR stock OR revenue)',
        "from": from_date,
        "sortBy": "relevancy",
        "language": "en",
        "pageSize": 20,
        "apiKey": NEWS_API_KEY,
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(NEWS_API_BASE, params=params)

        if response.status_code != 200:
            print(f"[News] HTTP {response.status_code} from NewsAPI")
            return []

        data = response.json()

    articles = []
    for item in data.get("articles", [])[:20]:
        article = NewsArticle(
            title=item.get("title", ""),
            description=item.get("description", ""),
            source_name=item.get("source", {}).get("name", ""),
            published_at=item.get("publishedAt", ""),
            content=item.get("content", item.get("description", "")),
            url=item.get("url", ""),
        )
        if article.title and article.title != "[Removed]":
            articles.append(article)

    return articles


# ---------------------------------------------------------------------------
# Sample Data Fallback
# ---------------------------------------------------------------------------

def _load_sample_news(symbol: str) -> list[NewsArticle] | None:
    """Load pre-cached sample news from the company's sample JSON file."""
    filepath = os.path.join(SAMPLE_DATA_DIR, f"{symbol}.json")
    if not os.path.exists(filepath):
        filepath = os.path.join(SAMPLE_DATA_DIR, f"{symbol.lower()}.json")
    if not os.path.exists(filepath):
        return None

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        news_data = data.get("news", [])
        return [NewsArticle.model_validate(a) for a in news_data]
    except Exception as e:
        print(f"[News] Failed to load sample news for {symbol}: {e}")
        return None


def get_company_name(symbol: str) -> str:
    """Get the full company name for a symbol."""
    return COMPANY_NAMES.get(symbol.upper(), symbol.upper())
