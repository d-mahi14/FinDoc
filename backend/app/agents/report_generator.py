"""
Report Generator Agent — compiles all agent outputs into a single structured report.

Takes outputs from Analyst, Red-Flag, Narrative, and Verifier agents
and assembles the final JSON report.
"""

import time
import uuid
from datetime import datetime

from app.models.schemas import (
    Report,
    ClaimWithVerification,
    VerificationResult,
    Verdict,
    NarrativeSummary,
    ExtractedFinancials,
    Ratio,
    RedFlag,
)
from app.utils.db import save_report, log_llm_usage


async def run_report_generator(
    symbol: str,
    job_id: str,
    company_name: str = "",
    extracted_financials: list[dict] = None,
    ratios: list[dict] = None,
    red_flags: list[dict] = None,
    narrative: dict = None,
    verification_results: list[dict] = None,
    agent_timings: list[dict] = None,
    data_sources: list[str] = None,
) -> dict:
    """
    Compile all agent outputs into a single structured report.
    Saves to SQLite and returns the report dict.
    """
    symbol = symbol.upper().strip()
    start_time = time.time()
    print(f"[ReportGen] Compiling report for {symbol} (job: {job_id})...")

    # -----------------------------------------------------------------------
    # Build the claims list with verification status
    # -----------------------------------------------------------------------
    all_claims = []

    # Claims from ratios (Analyst Agent)
    for ratio in (ratios or []):
        if isinstance(ratio, dict):
            claim_text = f"{ratio.get('name', '')}: {ratio.get('value', 'N/A')}{ratio.get('unit', '')}"
            if ratio.get('interpretation'):
                claim_text += f" — {ratio['interpretation']}"
        else:
            claim_text = f"{ratio.name}: {ratio.value}{ratio.unit}"

        # Find matching verification result
        verification = _find_verification(claim_text, verification_results)

        all_claims.append({
            "claim_text": claim_text,
            "claim_source": "analyst",
            "verification": verification,
        })

    # Claims from red flags
    for rf in (red_flags or []):
        if isinstance(rf, dict):
            claim_text = rf.get("explanation", rf.get("flag_name", ""))
        else:
            claim_text = rf.explanation or rf.flag_name

        verification = _find_verification(claim_text, verification_results)

        all_claims.append({
            "claim_text": claim_text,
            "claim_source": "red_flag",
            "verification": verification,
        })

    # Claims from narrative
    if narrative:
        narrative_claims = narrative.get("claims", []) if isinstance(narrative, dict) else narrative.claims
        for nc in narrative_claims:
            if isinstance(nc, dict):
                claim_text = nc.get("claim_text", "")
            else:
                claim_text = nc.claim_text

            verification = _find_verification(claim_text, verification_results)

            all_claims.append({
                "claim_text": claim_text,
                "claim_source": "narrative",
                "verification": verification,
            })

    # -----------------------------------------------------------------------
    # Calculate overall confidence
    # -----------------------------------------------------------------------
    confidences = [
        c["verification"].get("confidence", 0)
        for c in all_claims
        if c.get("verification")
    ]
    overall_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    # -----------------------------------------------------------------------
    # Build the overview text
    # -----------------------------------------------------------------------
    overview = _build_overview(symbol, company_name, ratios, red_flags, narrative)

    # -----------------------------------------------------------------------
    # Assemble the final report
    # -----------------------------------------------------------------------
    report_data = {
        "job_id": job_id,
        "symbol": symbol,
        "company_name": company_name or symbol,
        "generated_at": datetime.utcnow().isoformat(),
        "overview": overview,
        "financial_periods": extracted_financials or [],
        "ratios": ratios or [],
        "red_flags": red_flags or [],
        "narrative": narrative or {"claims": [], "overall_tone": "neutral", "summary_text": ""},
        "all_claims": all_claims,
        "overall_confidence": round(overall_confidence, 1),
        "data_sources_used": data_sources or [],
        "agent_timings": agent_timings or [],
    }

    # Save to SQLite
    await save_report(job_id, symbol, report_data)

    duration_ms = (time.time() - start_time) * 1000
    await log_llm_usage(
        agent_name="report_generator",
        model="none",
        latency_ms=duration_ms,
        symbol=symbol,
        job_id=job_id,
    )

    print(f"[ReportGen] Report compiled for {symbol}: {len(all_claims)} claims, "
          f"confidence={overall_confidence:.1f}% in {duration_ms:.0f}ms")

    return report_data


def _find_verification(claim_text: str, verification_results: list[dict] | None) -> dict:
    """Find the matching verification result for a claim."""
    if not verification_results:
        return {
            "verdict": Verdict.UNSUPPORTED.value,
            "confidence": 0,
            "source_excerpt": "",
            "explanation": "Not yet verified",
            "source_chunk_ids": [],
        }

    for vr in verification_results:
        if vr.get("claim_text", "") == claim_text:
            return {
                "claim_id": vr.get("claim_id", str(uuid.uuid4())),
                "claim_text": vr.get("claim_text", ""),
                "verdict": vr.get("verdict", Verdict.UNSUPPORTED.value),
                "confidence": vr.get("confidence", 0),
                "source_excerpt": vr.get("source_excerpt", ""),
                "explanation": vr.get("explanation", ""),
                "source_chunk_ids": vr.get("source_chunk_ids", []),
                "numeric_check_passed": vr.get("numeric_check_passed"),
            }

    # No exact match — return default
    return {
        "verdict": Verdict.UNSUPPORTED.value,
        "confidence": 0,
        "source_excerpt": "",
        "explanation": "No matching verification found",
        "source_chunk_ids": [],
    }


def _build_overview(
    symbol: str,
    company_name: str,
    ratios: list[dict] | None,
    red_flags: list[dict] | None,
    narrative: dict | None,
) -> str:
    """Build a human-readable overview paragraph."""
    parts = [f"{company_name or symbol} ({symbol}) — Due-Diligence Overview"]

    # Key metrics
    if ratios:
        rev_growth = next(
            (r for r in ratios if isinstance(r, dict) and "Revenue Growth" in r.get("name", "")),
            None
        )
        if rev_growth:
            parts.append(f"Revenue Growth: {rev_growth.get('value', 'N/A')}%")

        net_margin = next(
            (r for r in ratios if isinstance(r, dict) and "Net Profit Margin" in r.get("name", "")),
            None
        )
        if net_margin:
            parts.append(f"Net Margin: {net_margin.get('value', 'N/A')}%")

    # Red flags summary
    if red_flags:
        high = sum(1 for rf in red_flags if (rf.get("severity") if isinstance(rf, dict) else rf.severity) == "high")
        medium = sum(1 for rf in red_flags if (rf.get("severity") if isinstance(rf, dict) else rf.severity) == "medium")
        parts.append(f"Red Flags: {len(red_flags)} detected ({high} high, {medium} medium severity)")
    else:
        parts.append("Red Flags: None detected")

    # Narrative tone
    if narrative:
        tone = narrative.get("overall_tone", "neutral") if isinstance(narrative, dict) else narrative.overall_tone
        parts.append(f"Overall Narrative Tone: {tone}")

    return ". ".join(parts) + "."
