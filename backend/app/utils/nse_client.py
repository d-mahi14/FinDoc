"""
NSE/BSE client for fetching corporate filings and announcements.
Isolated module with 3-tier defense: SQLite cache → live fetch → sample data fallback.

WARNING: NSE does not provide an official public API. This module uses the unofficial
endpoints that the NSE website itself calls. These can change without notice.
"""

import json
import os
from datetime import datetime, timedelta
from typing import Any

import httpx

from app.models.schemas import Filing
from app.utils.db import cache_get, cache_set


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NSE_BASE_URL = "https://www.nseindia.com"
NSE_CORP_ANNOUNCEMENTS = f"{NSE_BASE_URL}/api/corporate-announcements"
NSE_COMPANY_INFO = f"{NSE_BASE_URL}/api/quote-equity"

SAMPLE_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "samples"
)

# NSE requires very specific headers to not reject requests
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/",
    "X-Requested-With": "XMLHttpRequest",
}


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------

async def fetch_filings(symbol: str, days: int = 90) -> list[Filing]:
    """
    Fetch recent corporate filings/announcements for a company.
    3-tier defense: cache → live → sample data.

    Returns a list of Filing objects — never raises on failure.
    """
    symbol = symbol.upper().strip()
    print(f"[NSE] Fetching filings for {symbol} (last {days} days)...")

    # Tier 1: SQLite cache
    cached = await cache_get("cached_filings", symbol)
    if cached:
        print(f"[NSE] Cache hit for {symbol}: {len(cached)} filings")
        return [Filing.model_validate(f) for f in cached]

    # Tier 2: Live fetch from NSE
    try:
        filings = await _fetch_nse_announcements(symbol, days)
        if filings:
            # Cache the results
            await cache_set(
                "cached_filings", symbol,
                [f.model_dump() for f in filings],
                ttl_hours=24, source="nse"
            )
            print(f"[NSE] Live data fetched for {symbol}: {len(filings)} filings")
            return filings
    except Exception as e:
        print(f"[NSE] Live fetch failed for {symbol}: {e}")

    # Tier 3: Sample data fallback
    sample_filings = _load_sample_filings(symbol)
    if sample_filings:
        await cache_set(
            "cached_filings", symbol,
            [f.model_dump() for f in sample_filings],
            ttl_hours=168, source="sample"
        )
        print(f"[NSE] Using sample filings for {symbol}: {len(sample_filings)}")
        return sample_filings

    print(f"[NSE] No filing data available for {symbol}")
    return []


# ---------------------------------------------------------------------------
# Live Fetcher
# ---------------------------------------------------------------------------

async def _fetch_nse_announcements(symbol: str, days: int = 90) -> list[Filing]:
    """Fetch announcements from NSE's unofficial API."""
    from_date = (datetime.now() - timedelta(days=days)).strftime("%d-%m-%Y")
    to_date = datetime.now().strftime("%d-%m-%Y")

    params = {
        "index": "equities",
        "symbol": symbol,
        "from_date": from_date,
        "to_date": to_date,
    }

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        # NSE requires a session — first hit the main page to get cookies
        try:
            pre_resp = await client.get(NSE_BASE_URL, headers=HEADERS)
            cookies = dict(pre_resp.cookies)
        except Exception:
            cookies = {}

        response = await client.get(
            NSE_CORP_ANNOUNCEMENTS,
            params=params,
            headers=HEADERS,
            cookies=cookies,
        )

        if response.status_code != 200:
            print(f"[NSE] HTTP {response.status_code} for announcements")
            return []

        try:
            data = response.json()
        except Exception:
            return []

    filings = []
    items = data if isinstance(data, list) else data.get("data", data.get("results", []))

    for item in items[:50]:  # Limit to 50 most recent
        filing = Filing(
            date=item.get("an_dt", item.get("date", "")),
            title=item.get("desc", item.get("subject", item.get("title", ""))),
            category=item.get("attchmntFile", item.get("category", "")),
            content_text=item.get("desc", "") + " " + item.get("attchmntText", ""),
            url=item.get("attchmntFile", ""),
            source="nse",
        )
        filings.append(filing)

    return filings


# ---------------------------------------------------------------------------
# Sample Data Fallback
# ---------------------------------------------------------------------------

def _load_sample_filings(symbol: str) -> list[Filing] | None:
    """Load pre-cached sample filings from the company's sample JSON file."""
    filepath = os.path.join(SAMPLE_DATA_DIR, f"{symbol}.json")
    if not os.path.exists(filepath):
        filepath = os.path.join(SAMPLE_DATA_DIR, f"{symbol.lower()}.json")
    if not os.path.exists(filepath):
        return None

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        filings_data = data.get("filings", [])
        return [Filing.model_validate(f) for f in filings_data]
    except Exception as e:
        print(f"[NSE] Failed to load sample filings for {symbol}: {e}")
        return None
