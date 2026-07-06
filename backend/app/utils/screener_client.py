"""
Screener.in client for fetching Indian company financial data.
Isolated module with 3-tier defense: SQLite cache → live scrape → sample data fallback.

WARNING: Screener.in has no official API. This module scrapes the public company page
using session cookies. It's the most fragile data source — aggressive caching is critical.
"""

import json
import os
from datetime import datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.models.schemas import FinancialData, FinancialPeriod
from app.utils.db import cache_get, cache_set


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCREENER_BASE_URL = "https://www.screener.in/company"
SESSION_TOKEN = os.getenv("SCREENER_SESSION_TOKEN", "")
SAMPLE_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "samples"
)

# Common headers to mimic browser requests
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.screener.in/",
}


# Symbol → Screener slug mapping for common companies
SYMBOL_MAP = {
    "TCS": "TCS/consolidated/",
    "RELIANCE": "RELIANCE/consolidated/",
    "INFY": "INFY/consolidated/",
    "HDFCBANK": "HDFCBANK/consolidated/",
    "WIPRO": "WIPRO/consolidated/",
    "ICICIBANK": "ICICIBANK/consolidated/",
    "ITC": "ITC/consolidated/",
    "SBIN": "SBIN/consolidated/",
    "BAJFINANCE": "BAJFINANCE/consolidated/",
    "LT": "LT/consolidated/",
}


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------

async def fetch_financials(symbol: str) -> FinancialData:
    """
    Fetch financial data for a company with 3-tier defense:
    1. Check SQLite cache (TTL: 24 hours)
    2. Attempt live scrape from Screener.in
    3. Fallback to pre-cached sample data

    Always returns a FinancialData object — never raises on data source failure.
    """
    symbol = symbol.upper().strip()
    print(f"[Screener] Fetching financials for {symbol}...")

    # Tier 1: SQLite cache
    cached = await cache_get("cached_financials", symbol)
    if cached:
        print(f"[Screener] Cache hit for {symbol}")
        return FinancialData.model_validate(cached)

    # Tier 2: Live scrape
    try:
        data = await _scrape_screener(symbol)
        if data and data.periods:
            # Cache the result
            await cache_set("cached_financials", symbol, data.model_dump(), ttl_hours=24, source="screener")
            print(f"[Screener] Live data fetched for {symbol}: {len(data.periods)} periods")
            return data
    except Exception as e:
        print(f"[Screener] Live scrape failed for {symbol}: {e}")

    # Tier 3: Sample data fallback
    sample_data = _load_sample_data(symbol)
    if sample_data:
        # Cache the sample data too (so subsequent calls are faster)
        await cache_set("cached_financials", symbol, sample_data.model_dump(), ttl_hours=168, source="sample")
        print(f"[Screener] Using sample data for {symbol}")
        return sample_data

    # Last resort: return empty but valid FinancialData
    print(f"[Screener] No data available for {symbol} — returning empty")
    return FinancialData(symbol=symbol, company_name=symbol, source="empty")


# ---------------------------------------------------------------------------
# Live Scraper
# ---------------------------------------------------------------------------

async def _scrape_screener(symbol: str) -> FinancialData | None:
    """Attempt to scrape financial data from Screener.in."""
    slug = SYMBOL_MAP.get(symbol, f"{symbol}/consolidated/")
    url = f"{SCREENER_BASE_URL}/{slug}"

    cookies = {}
    if SESSION_TOKEN:
        cookies["sessionid"] = SESSION_TOKEN

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(url, headers=HEADERS, cookies=cookies)

        if response.status_code != 200:
            print(f"[Screener] HTTP {response.status_code} for {url}")
            return None

        return _parse_screener_html(symbol, response.text)


def _parse_screener_html(symbol: str, html: str) -> FinancialData | None:
    """Parse the Screener.in company page HTML into structured financial data."""
    soup = BeautifulSoup(html, "lxml")

    # Extract company name
    name_el = soup.select_one("h1.margin-0")
    company_name = name_el.get_text(strip=True) if name_el else symbol

    # Extract sector
    sector = ""
    sector_el = soup.select_one("a[href*='/screen/raw/']")
    if sector_el:
        sector = sector_el.get_text(strip=True)

    # Parse financial tables (P&L, Balance Sheet, Cash Flow)
    raw_tables = {}
    periods = []

    for section_id, section_name in [
        ("profit-loss", "P&L"),
        ("balance-sheet", "BalanceSheet"),
        ("cash-flow", "CashFlow"),
    ]:
        section_el = soup.find("section", id=section_id)
        if section_el:
            table = section_el.find("table")
            if table:
                parsed = _parse_financial_table(table)
                raw_tables[section_name] = parsed

    # Merge tables into FinancialPeriod objects
    periods = _merge_tables_to_periods(raw_tables)

    if not periods and not raw_tables:
        return None

    return FinancialData(
        symbol=symbol,
        company_name=company_name,
        sector=sector,
        periods=periods,
        raw_tables=raw_tables,
        source="screener",
    )


def _parse_financial_table(table) -> dict[str, list]:
    """
    Parse a Screener.in HTML table into a dict of:
    { "headers": [...periods...], "rows": { "Revenue": [...values...], ... } }
    """
    result = {"headers": [], "rows": {}}

    # Header row (period labels)
    thead = table.find("thead")
    if thead:
        header_cells = thead.find_all("th")
        result["headers"] = [cell.get_text(strip=True) for cell in header_cells[1:]]  # Skip label column

    # Data rows
    tbody = table.find("tbody")
    if tbody:
        for row in tbody.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            label = cells[0].get_text(strip=True)
            values = []
            for cell in cells[1:]:
                text = cell.get_text(strip=True).replace(",", "").replace("%", "")
                try:
                    values.append(float(text))
                except (ValueError, TypeError):
                    values.append(None)
            result["rows"][label] = values

    return result


def _merge_tables_to_periods(raw_tables: dict) -> list[FinancialPeriod]:
    """Merge P&L, Balance Sheet, and Cash Flow tables into unified period objects."""
    # Get period headers from P&L (or whatever is available)
    headers = []
    for section_name in ["P&L", "BalanceSheet", "CashFlow"]:
        if section_name in raw_tables and raw_tables[section_name].get("headers"):
            headers = raw_tables[section_name]["headers"]
            break

    if not headers:
        return []

    periods = []
    for i, period_label in enumerate(headers):
        fp = FinancialPeriod(period=period_label)

        # P&L data
        pl = raw_tables.get("P&L", {}).get("rows", {})
        fp.revenue = _safe_get(pl, ["Sales", "Revenue", "Revenue from Operations", "Net Sales", "Total Revenue"], i)
        fp.net_profit = _safe_get(pl, ["Net Profit", "PAT", "Profit after Tax", "Net Income"], i)
        fp.operating_profit = _safe_get(pl, ["Operating Profit", "EBIT", "EBITDA", "Profit before Interest and Tax"], i)

        # Balance Sheet data
        bs = raw_tables.get("BalanceSheet", {}).get("rows", {})
        fp.total_equity = _safe_get(bs, ["Total Equity", "Equity", "Shareholders' Funds", "Share Capital + Reserves"], i)
        fp.total_debt = _safe_get(bs, ["Borrowings", "Total Debt", "Long Term Borrowings", "Total Borrowings"], i)
        fp.total_assets = _safe_get(bs, ["Total Assets", "Total"], i)
        fp.total_liabilities = _safe_get(bs, ["Total Liabilities", "Total Liabilities and Equity"], i)
        fp.current_assets = _safe_get(bs, ["Total Current Assets", "Current Assets"], i)
        fp.current_liabilities = _safe_get(bs, ["Total Current Liabilities", "Current Liabilities"], i)
        fp.inventory = _safe_get(bs, ["Inventories", "Inventory"], i)

        # Cash Flow data
        cf = raw_tables.get("CashFlow", {}).get("rows", {})
        fp.operating_cash_flow = _safe_get(cf, [
            "Cash from Operating Activity",
            "Operating Cash Flow",
            "Net Cash from Operations",
            "Cash from Operations"
        ], i)

        periods.append(fp)

    return periods


def _safe_get(rows: dict, keys: list[str], index: int) -> float | None:
    """Try multiple possible row labels and return the value at the given index."""
    for key in keys:
        if key in rows:
            values = rows[key]
            if index < len(values):
                return values[index]
    return None


# ---------------------------------------------------------------------------
# Sample Data Fallback
# ---------------------------------------------------------------------------

def _load_sample_data(symbol: str) -> FinancialData | None:
    """Load pre-cached sample data from JSON files."""
    filepath = os.path.join(SAMPLE_DATA_DIR, f"{symbol}.json")
    if not os.path.exists(filepath):
        # Try lowercase
        filepath = os.path.join(SAMPLE_DATA_DIR, f"{symbol.lower()}.json")
    if not os.path.exists(filepath):
        return None

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return FinancialData.model_validate(data)
    except Exception as e:
        print(f"[Screener] Failed to load sample data for {symbol}: {e}")
        return None


def get_available_sample_symbols() -> list[str]:
    """List all symbols that have pre-cached sample data."""
    if not os.path.exists(SAMPLE_DATA_DIR):
        return []
    return [
        f.replace(".json", "").upper()
        for f in os.listdir(SAMPLE_DATA_DIR)
        if f.endswith(".json")
    ]
