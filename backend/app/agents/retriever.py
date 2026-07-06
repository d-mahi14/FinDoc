"""
Retriever Agent — fetches financial data, filings, and news for a company,
then chunks all text and stores in ChromaDB for downstream agent consumption.

No LLM used. Purely data fetch + rule-based chunking + embedding.
"""

import time
from typing import Any

from app.models.schemas import (
    FinancialData,
    Filing,
    NewsArticle,
    RetrieveResponse,
)
from app.utils.screener_client import fetch_financials
from app.utils.nse_client import fetch_filings
from app.utils.news_client import fetch_news
from app.utils.vector_store import chunk_text, add_chunks, delete_company_chunks
from app.utils.db import log_llm_usage


async def run_retriever(symbol: str, force_refresh: bool = False) -> dict:
    """
    Main entry point for the Retriever Agent.

    1. Fetches financials (Screener), filings (NSE), news (NewsAPI)
    2. Chunks all text (~500 tokens each) with metadata
    3. Embeds & stores in ChromaDB

    Returns a summary dict compatible with RetrieveResponse.
    """
    symbol = symbol.upper().strip()
    start_time = time.time()
    print(f"[Retriever] Starting retrieval for {symbol}...")

    # Optionally clear existing chunks for fresh re-indexing
    if force_refresh:
        deleted = delete_company_chunks(symbol)
        print(f"[Retriever] Cleared {deleted} existing chunks for {symbol}")

    # -----------------------------------------------------------------------
    # Step 1: Fetch data from all sources (parallel-safe, each has own cache)
    # -----------------------------------------------------------------------
    financial_data: FinancialData = await fetch_financials(symbol)
    filings: list[Filing] = await fetch_filings(symbol)
    news_articles: list[NewsArticle] = await fetch_news(symbol)

    # -----------------------------------------------------------------------
    # Step 2: Convert to text and chunk
    # -----------------------------------------------------------------------
    all_chunks = []

    # 2a. Financial table data → text chunks
    financial_chunks = _chunk_financial_data(financial_data, symbol)
    all_chunks.extend(financial_chunks)

    # 2b. Filings → text chunks
    filing_chunks = _chunk_filings(filings, symbol)
    all_chunks.extend(filing_chunks)

    # 2c. News articles → text chunks
    news_chunks = _chunk_news(news_articles, symbol)
    all_chunks.extend(news_chunks)

    # -----------------------------------------------------------------------
    # Step 3: Store in ChromaDB
    # -----------------------------------------------------------------------
    chunks_indexed = 0
    if all_chunks:
        chunks_indexed = add_chunks(symbol, all_chunks)

    duration_ms = (time.time() - start_time) * 1000

    # Log as a non-LLM agent call for consistency
    await log_llm_usage(
        agent_name="retriever",
        model="none",
        input_tokens=0,
        output_tokens=0,
        latency_ms=duration_ms,
        symbol=symbol,
    )

    result = {
        "symbol": symbol,
        "company_name": financial_data.company_name,
        "chunks_indexed": chunks_indexed,
        "financial_periods_found": len(financial_data.periods),
        "filings_found": len(filings),
        "news_articles_found": len(news_articles),
        "source": financial_data.source,
        "duration_ms": round(duration_ms, 1),
    }

    print(f"[Retriever] Completed for {symbol}: {chunks_indexed} chunks indexed "
          f"in {duration_ms:.0f}ms")

    return result


def _chunk_financial_data(data: FinancialData, symbol: str) -> list:
    """Convert structured financial data into text chunks for embedding."""
    chunks = []

    if not data.periods:
        return chunks

    # Create a comprehensive text representation of each financial section
    for section_name, section_key in [
        ("Profit & Loss Statement", "P&L"),
        ("Balance Sheet", "BalanceSheet"),
        ("Cash Flow Statement", "CashFlow"),
    ]:
        section_data = data.raw_tables.get(section_key, {})
        if not section_data:
            continue

        headers = section_data.get("headers", [])
        rows = section_data.get("rows", {})

        if not headers or not rows:
            continue

        # Build readable text from table
        text_parts = [
            f"{data.company_name} ({symbol}) — {section_name}",
            f"Periods: {', '.join(headers)}",
            "",
        ]

        for row_label, values in rows.items():
            formatted_vals = []
            for v in values:
                if v is None:
                    formatted_vals.append("N/A")
                elif isinstance(v, float) and v >= 1000:
                    formatted_vals.append(f"₹{v:,.0f} Cr")
                elif isinstance(v, float):
                    formatted_vals.append(f"{v:.1f}")
                else:
                    formatted_vals.append(str(v))
            text_parts.append(f"{row_label}: {' | '.join(formatted_vals)}")

        section_text = "\n".join(text_parts)

        section_chunks = chunk_text(
            text=section_text,
            max_tokens=500,
            overlap_tokens=50,
            metadata={
                "source_type": "financials",
                "document_date": headers[0] if headers else "",
                "section": section_key,
                "original_source": f"screener/{symbol}",
            },
            company_symbol=symbol,
        )
        chunks.extend(section_chunks)

    # Also create a summary chunk with key metrics per period
    if data.periods:
        summary_parts = [
            f"{data.company_name} ({symbol}) — Financial Summary",
            f"Sector: {data.sector or 'N/A'}",
            f"Data source: {data.source}",
            "",
        ]
        for period in data.periods:
            parts = [f"Period: {period.period}"]
            if period.revenue is not None:
                parts.append(f"Revenue: ₹{period.revenue:,.0f} Cr")
            if period.net_profit is not None:
                parts.append(f"Net Profit: ₹{period.net_profit:,.0f} Cr")
            if period.operating_profit is not None:
                parts.append(f"Operating Profit: ₹{period.operating_profit:,.0f} Cr")
            if period.operating_cash_flow is not None:
                parts.append(f"Operating Cash Flow: ₹{period.operating_cash_flow:,.0f} Cr")
            if period.total_debt is not None:
                parts.append(f"Total Debt: ₹{period.total_debt:,.0f} Cr")
            if period.total_equity is not None:
                parts.append(f"Total Equity: ₹{period.total_equity:,.0f} Cr")
            if period.inventory is not None:
                parts.append(f"Inventory: ₹{period.inventory:,.0f} Cr")
            summary_parts.append(" | ".join(parts))

        summary_text = "\n".join(summary_parts)
        summary_chunks = chunk_text(
            text=summary_text,
            max_tokens=500,
            overlap_tokens=50,
            metadata={
                "source_type": "financials",
                "document_date": data.periods[0].period if data.periods else "",
                "section": "Summary",
                "original_source": f"screener/{symbol}",
            },
            company_symbol=symbol,
        )
        chunks.extend(summary_chunks)

    return chunks


def _chunk_filings(filings: list[Filing], symbol: str) -> list:
    """Convert filings into text chunks for embedding."""
    chunks = []

    for filing in filings:
        text = (
            f"Filing: {filing.title}\n"
            f"Date: {filing.date}\n"
            f"Category: {filing.category}\n"
            f"Source: {filing.source}\n\n"
            f"{filing.content_text}"
        )

        filing_chunks = chunk_text(
            text=text,
            max_tokens=500,
            overlap_tokens=50,
            metadata={
                "source_type": "filing",
                "document_date": filing.date,
                "section": filing.category,
                "original_source": filing.url or f"nse/{symbol}",
            },
            company_symbol=symbol,
        )
        chunks.extend(filing_chunks)

    return chunks


def _chunk_news(articles: list[NewsArticle], symbol: str) -> list:
    """Convert news articles into text chunks for embedding."""
    chunks = []

    for article in articles:
        text = (
            f"News: {article.title}\n"
            f"Source: {article.source_name}\n"
            f"Published: {article.published_at}\n\n"
            f"{article.content or article.description}"
        )

        article_chunks = chunk_text(
            text=text,
            max_tokens=500,
            overlap_tokens=50,
            metadata={
                "source_type": "news",
                "document_date": article.published_at[:10] if article.published_at else "",
                "section": "news",
                "original_source": article.url or article.source_name,
            },
            company_symbol=symbol,
        )
        chunks.extend(article_chunks)

    return chunks
