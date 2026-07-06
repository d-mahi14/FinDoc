"""
Critic/Verifier Agent — the core trust layer.

For every claim from Analyst, Red-Flag, and Sentiment agents:
1. Re-retrieves the cited source chunk from ChromaDB
2. Runs an entailment check via Gemini structured output
3. Applies numeric tolerance logic (within 2% = SUPPORTED)

Ensures no hallucinated claims pass through to the final report.
"""

import re
import time
from typing import Any

from app.models.schemas import (
    VerificationResult,
    Verdict,
    GeminiEntailmentResult,
    ClaimWithVerification,
)
from app.utils.llm_client import get_llm_client
from app.utils.vector_store import get_chunks_by_ids, query_chunks
from app.utils.db import log_llm_usage


async def run_verifier(claims: list[dict], symbol: str = "") -> list[dict]:
    """
    Main entry point for the Verifier Agent.

    Accepts a list of claims, each with:
        - claim_text: str
        - source_chunk_ids: list[str] (optional)
        - claim_source: str  ("analyst", "red_flag", "narrative")

    Returns a list of VerificationResult dicts.
    """
    symbol = symbol.upper().strip()
    start_time = time.time()
    print(f"[Verifier] Starting verification of {len(claims)} claims for {symbol}...")

    llm = get_llm_client()
    results = []

    for claim in claims:
        claim_text = claim.get("claim_text", "")
        source_chunk_ids = claim.get("source_chunk_ids", [])
        claim_source = claim.get("claim_source", "unknown")

        if not claim_text:
            continue

        result = await _verify_single_claim(
            llm=llm,
            claim_text=claim_text,
            source_chunk_ids=source_chunk_ids,
            symbol=symbol,
        )
        result["claim_text"] = claim_text
        result["claim_source"] = claim_source
        results.append(result)

    duration_ms = (time.time() - start_time) * 1000
    await log_llm_usage(
        agent_name="verifier",
        model="aggregate",
        latency_ms=duration_ms,
        symbol=symbol,
    )

    print(f"[Verifier] Completed: {len(results)} claims verified in {duration_ms:.0f}ms")
    return results


async def verify_single_claim(claim_text: str, source_chunk_ids: list[str], symbol: str) -> dict:
    """Verify a single claim on demand (for re-verification)."""
    llm = get_llm_client()
    result = await _verify_single_claim(llm, claim_text, source_chunk_ids, symbol)
    result["claim_text"] = claim_text
    return result


async def _verify_single_claim(
    llm,
    claim_text: str,
    source_chunk_ids: list[str],
    symbol: str,
) -> dict:
    """
    Verify a single claim by:
    1. Re-retrieving cited source chunks
    2. Running LLM entailment check
    3. Applying numeric tolerance
    """
    # Step 1: Get source evidence
    source_text = ""
    source_excerpt = ""

    if source_chunk_ids:
        chunks = get_chunks_by_ids(source_chunk_ids[:5])  # Limit to 5 most relevant
        if chunks:
            source_text = "\n\n".join([c.get("text", "") for c in chunks])
            source_excerpt = source_text[:500]  # First 500 chars for the report

    # If no chunks found via IDs, try semantic search
    if not source_text and symbol:
        fallback_chunks = query_chunks(
            company_symbol=symbol,
            query=claim_text,
            n_results=5,
        )
        if fallback_chunks:
            source_text = "\n\n".join([c.get("text", "") for c in fallback_chunks])
            source_excerpt = source_text[:500]
            source_chunk_ids = [c["chunk_id"] for c in fallback_chunks]

    if not source_text:
        return {
            "verdict": Verdict.UNSUPPORTED.value,
            "confidence": 10,
            "source_excerpt": "",
            "explanation": "No source data found to verify this claim.",
            "source_chunk_ids": [],
            "numeric_check_passed": None,
        }

    # Step 2: Numeric tolerance check (code-based, before LLM)
    numeric_check = _check_numeric_tolerance(claim_text, source_text)

    # Step 3: LLM entailment check
    llm_result = None
    if llm.is_configured():
        try:
            llm_result = _run_entailment_check(llm, claim_text, source_text)
        except Exception as e:
            print(f"[Verifier] LLM entailment check failed: {e}")

    # Combine results
    if llm_result:
        verdict = llm_result.get("verdict", Verdict.UNSUPPORTED.value)
        confidence = llm_result.get("confidence", 50)
        explanation = llm_result.get("explanation", "")

        # Override with numeric check if it's definitive
        if numeric_check is not None:
            if not numeric_check and verdict == Verdict.SUPPORTED.value:
                verdict = Verdict.CONTRADICTED.value
                confidence = max(confidence - 20, 10)
                explanation += " [Numeric check: values differ by >2%]"
            elif numeric_check and verdict != Verdict.SUPPORTED.value:
                # Numeric match but LLM says unsupported — trust the numbers
                verdict = Verdict.SUPPORTED.value
                confidence = min(confidence + 15, 95)
                explanation += " [Numeric check: values match within 2% tolerance]"
    else:
        # Fallback: use numeric check only
        if numeric_check is True:
            verdict = Verdict.SUPPORTED.value
            confidence = 70
            explanation = "LLM unavailable. Numeric values match within 2% tolerance."
        elif numeric_check is False:
            verdict = Verdict.CONTRADICTED.value
            confidence = 60
            explanation = "LLM unavailable. Numeric values differ by more than 2%."
        else:
            verdict = Verdict.UNSUPPORTED.value
            confidence = 30
            explanation = "LLM unavailable and no numeric values to verify."

    return {
        "verdict": verdict,
        "confidence": confidence,
        "source_excerpt": source_excerpt,
        "explanation": explanation,
        "source_chunk_ids": source_chunk_ids,
        "numeric_check_passed": numeric_check,
    }


def _run_entailment_check(llm, claim_text: str, source_text: str) -> dict:
    """Run LLM entailment check via Gemini structured output."""
    prompt = f"""You are a fact-checking agent for financial claims. Determine if the CLAIM is 
supported by, unsupported by, or contradicted by the SOURCE EVIDENCE.

Rules:
- SUPPORTED: The claim is directly stated in or clearly implied by the source evidence
- UNSUPPORTED: The source evidence doesn't contain enough information to verify the claim
- CONTRADICTED: The source evidence contains information that directly conflicts with the claim
- For numeric claims, allow a 2% tolerance margin (e.g., if claim says "₹240,893 Cr" and source says "₹240,890 Cr", that's SUPPORTED)
- A numeric claim with the wrong direction (growth vs decline) is always CONTRADICTED

CLAIM: {claim_text}

SOURCE EVIDENCE:
{source_text}"""

    result = llm.generate_structured(
        message=prompt,
        response_schema=GeminiEntailmentResult,
        agent_name="verifier_entailment",
        system_instruction="You are a precise fact-checker. Only mark SUPPORTED if the evidence clearly backs the claim.",
    )

    return {
        "verdict": result.verdict if hasattr(result, 'verdict') else "UNSUPPORTED",
        "confidence": result.confidence if hasattr(result, 'confidence') else 50,
        "explanation": result.explanation if hasattr(result, 'explanation') else "",
    }


def _check_numeric_tolerance(claim_text: str, source_text: str) -> bool | None:
    """
    Code-based numeric tolerance check.
    Extracts numbers from claim and source, checks if they match within 2%.
    Returns True (match), False (mismatch), or None (no numbers to compare).
    """
    # Extract numbers from claim (look for ₹ amounts, percentages, ratios)
    claim_numbers = _extract_numbers(claim_text)
    if not claim_numbers:
        return None  # No numeric content to check

    source_numbers = _extract_numbers(source_text)
    if not source_numbers:
        return None  # No source numbers to compare against

    # For each claim number, check if a matching number exists in source
    matched = 0
    total = 0

    for cn in claim_numbers:
        total += 1
        for sn in source_numbers:
            if sn == 0 and cn == 0:
                matched += 1
                break
            elif sn != 0:
                diff_pct = abs(cn - sn) / abs(sn) * 100
                if diff_pct <= 2.0:
                    matched += 1
                    break

    if total == 0:
        return None

    # If at least 60% of claim numbers match source, consider it passing
    return (matched / total) >= 0.6


def _extract_numbers(text: str) -> list[float]:
    """Extract numeric values from text, handling ₹, Cr, %, commas."""
    numbers = []

    # Pattern: numbers with optional commas, decimals, and currency symbols
    patterns = [
        r'₹?\s*([\d,]+(?:\.\d+)?)\s*(?:Cr|crore|cr)',  # ₹ X Cr
        r'([\d,]+(?:\.\d+)?)\s*%',  # X%
        r'₹?\s*([\d,]+(?:\.\d+)?)',  # plain numbers
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            try:
                val = float(match.replace(",", ""))
                if val > 0:  # Skip zeros and negatives for matching
                    numbers.append(val)
            except (ValueError, TypeError):
                continue

    return list(set(numbers))  # Deduplicate
