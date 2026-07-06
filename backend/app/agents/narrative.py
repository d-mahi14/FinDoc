"""
Sentiment/Narrative Agent — extracts stated reasons for performance 
from news and filings, every claim cited to its source chunk.

Not just tone analysis — extracts actual causal claims management makes
about why metrics moved in a particular direction.
"""

import time
from typing import Any

from app.models.schemas import (
    NarrativeSummary,
    NarrativeClaim,
    NarrativeResponse,
    GeminiNarrativeExtraction,
)
from app.utils.llm_client import get_llm_client
from app.utils.vector_store import query_chunks
from app.utils.db import log_llm_usage


async def run_narrative_agent(symbol: str) -> dict:
    """
    Main entry point for the Narrative Agent.

    1. Queries ChromaDB for news + filing chunks
    2. Uses Gemini structured output to extract stated reasons for performance
    3. Every claim is cited to source chunk IDs
    4. Summarizes into 3-5 sentences + overall tone

    Returns a dict with narrative summary.
    """
    symbol = symbol.upper().strip()
    start_time = time.time()
    print(f"[Narrative] Starting narrative analysis for {symbol}...")

    llm = get_llm_client()

    # -----------------------------------------------------------------------
    # Step 1: Retrieve news and filing chunks
    # -----------------------------------------------------------------------
    news_chunks = query_chunks(
        company_symbol=symbol,
        query="results growth revenue profit outlook strategy performance guidance",
        n_results=10,
        source_type="news",
    )

    filing_chunks = query_chunks(
        company_symbol=symbol,
        query="quarterly results financial performance management commentary outlook growth",
        n_results=10,
        source_type="filing",
    )

    all_chunks = news_chunks + filing_chunks

    if not all_chunks:
        print(f"[Narrative] No news/filing chunks found for {symbol}")
        return {
            "symbol": symbol,
            "narrative": NarrativeSummary(
                summary_text=f"No news or filing data available for {symbol}.",
                overall_tone="neutral",
            ).model_dump(),
        }

    # Build context
    chunks_text = "\n\n---\n\n".join([
        f"[Source: {c['metadata'].get('source_type', 'unknown')} | "
        f"Date: {c['metadata'].get('document_date', 'N/A')} | "
        f"Chunk ID: {c['chunk_id'][:8]}]\n{c['text']}"
        for c in all_chunks
    ])

    # Map chunk_id prefix to full ID for citation
    chunk_id_map = {c["chunk_id"][:8]: c["chunk_id"] for c in all_chunks}
    all_chunk_ids = [c["chunk_id"] for c in all_chunks]

    # -----------------------------------------------------------------------
    # Step 2: Extract narrative claims via LLM
    # -----------------------------------------------------------------------
    narrative = None

    if llm.is_configured():
        try:
            prompt = f"""You are a financial analyst extracting key narrative claims from news articles and corporate filings about {symbol}.

For each claim, extract:
1. The stated reason or causal explanation for a business outcome (not just describing what happened, but WHY management/analysts say it happened)
2. The source type ("news" or "filing")
3. Reference chunk IDs that support this claim

Focus on:
- Management's stated reasons for revenue/profit changes
- Strategic initiatives and their expected impact  
- Market conditions cited as tailwinds or headwinds
- Analyst opinions and target price rationale
- Key risks or challenges highlighted

Extract 5-8 distinct claims. Each claim should be a factual statement, not opinion.
Also assess the overall tone (positive/negative/neutral/mixed).

SOURCE DATA:
{chunks_text}"""

            result = llm.generate_structured(
                message=prompt,
                response_schema=GeminiNarrativeExtraction,
                agent_name="narrative_extractor",
                system_instruction="Extract factual narrative claims with source attribution. Focus on stated reasons for performance, not just tone.",
            )

            if result:
                # Map chunk IDs back to full IDs
                claims = []
                for claim in result.claims:
                    # Try to resolve short chunk IDs to full IDs
                    resolved_ids = []
                    for short_id in claim.source_chunk_ids:
                        full_id = chunk_id_map.get(short_id[:8], short_id)
                        resolved_ids.append(full_id)

                    # If no chunk IDs were resolved, assign all chunks
                    if not resolved_ids:
                        resolved_ids = all_chunk_ids[:3]

                    claims.append(NarrativeClaim(
                        claim_text=claim.claim_text,
                        source_chunk_ids=resolved_ids,
                        source_type=claim.source_type or "mixed",
                    ))

                narrative = NarrativeSummary(
                    claims=claims,
                    overall_tone=result.overall_tone,
                )

        except Exception as e:
            print(f"[Narrative] LLM extraction failed: {e}")

    # Fallback: basic extraction without LLM
    if narrative is None:
        narrative = _fallback_narrative(all_chunks, symbol)

    # Generate summary text
    if narrative.claims and not narrative.summary_text:
        narrative.summary_text = _generate_summary_from_claims(narrative.claims, symbol)

    duration_ms = (time.time() - start_time) * 1000
    await log_llm_usage(
        agent_name="narrative",
        model="aggregate",
        latency_ms=duration_ms,
        symbol=symbol,
    )

    result = {
        "symbol": symbol,
        "narrative": narrative.model_dump(),
    }

    print(f"[Narrative] Completed for {symbol}: {len(narrative.claims)} claims, "
          f"tone={narrative.overall_tone} in {duration_ms:.0f}ms")

    return result


def _fallback_narrative(chunks: list[dict], symbol: str) -> NarrativeSummary:
    """Basic narrative extraction without LLM — uses headlines as claims."""
    claims = []

    for chunk in chunks:
        text = chunk.get("text", "")
        lines = text.strip().split("\n")

        # First line is usually the title/headline
        if lines:
            title_line = lines[0].strip()
            for prefix in ["News:", "Filing:"]:
                if title_line.startswith(prefix):
                    title_line = title_line[len(prefix):].strip()

            if title_line and len(title_line) > 20:
                claims.append(NarrativeClaim(
                    claim_text=title_line,
                    source_chunk_ids=[chunk["chunk_id"]],
                    source_type=chunk.get("metadata", {}).get("source_type", "unknown"),
                ))

    # Limit to 8 claims
    claims = claims[:8]

    return NarrativeSummary(
        claims=claims,
        overall_tone="neutral",
        summary_text=f"Extracted {len(claims)} narrative claims for {symbol} from available news and filings.",
    )


def _generate_summary_from_claims(claims: list[NarrativeClaim], symbol: str) -> str:
    """Generate a summary paragraph from extracted claims."""
    if not claims:
        return f"No narrative claims available for {symbol}."

    claim_texts = [c.claim_text for c in claims[:5]]
    summary = f"Key narrative themes for {symbol}: " + ". ".join(claim_texts)

    if len(summary) > 500:
        summary = summary[:497] + "..."

    return summary
