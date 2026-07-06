"""
API routes for the Verifier Agent.
POST /api/verify — verify claims against source data.
POST /api/reverify/{job_id}/{claim_id} — re-verify a single claim.
"""

import uuid

# pyrefly: ignore [missing-import]
from fastapi import APIRouter, HTTPException

from app.agents.verifier import run_verifier, verify_single_claim
from app.models.schemas import VerifyRequest, VerifyResponse, VerificationResult
from app.utils.db import get_report, save_report


router = APIRouter()


@router.post("/verify", response_model=VerifyResponse)
async def verify_claims(request: VerifyRequest):
    """Verify a list of claims against source data in ChromaDB."""
    if not request.claims:
        raise HTTPException(status_code=400, detail="No claims provided")

    try:
        results = await run_verifier(request.claims, request.symbol)
        verification_results = []
        for r in results:
            verification_results.append(VerificationResult(
                claim_id=r.get("claim_id", str(uuid.uuid4())),
                claim_text=r.get("claim_text", ""),
                verdict=r.get("verdict", "UNSUPPORTED"),
                confidence=r.get("confidence", 0),
                source_excerpt=r.get("source_excerpt", ""),
                explanation=r.get("explanation", ""),
                source_chunk_ids=r.get("source_chunk_ids", []),
                numeric_check_passed=r.get("numeric_check_passed"),
            ))
        return VerifyResponse(results=verification_results)
    except Exception as e:
        print(f"[Route] Verify error: {e}")
        raise HTTPException(status_code=500, detail=f"Verification failed: {str(e)}")


@router.post("/reverify/{job_id}/{claim_id}")
async def reverify_claim(job_id: str, claim_id: str):
    """Re-verify a single claim from an existing report."""
    # Get the report
    report = await get_report(job_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Report not found for job {job_id}")

    # Find the claim
    symbol = report.get("symbol", "")
    target_claim = None

    for claim in report.get("all_claims", []):
        v = claim.get("verification", {})
        if v.get("claim_id") == claim_id or claim.get("claim_text", "")[:50] == claim_id[:50]:
            target_claim = claim
            break

    if not target_claim:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found in report")

    # Re-verify
    try:
        result = await verify_single_claim(
            claim_text=target_claim["claim_text"],
            source_chunk_ids=target_claim.get("verification", {}).get("source_chunk_ids", []),
            symbol=symbol,
        )

        # Update the report with new verification
        new_verification = VerificationResult(
            claim_id=claim_id,
            claim_text=result.get("claim_text", ""),
            verdict=result.get("verdict", "UNSUPPORTED"),
            confidence=result.get("confidence", 0),
            source_excerpt=result.get("source_excerpt", ""),
            explanation=result.get("explanation", ""),
            source_chunk_ids=result.get("source_chunk_ids", []),
            numeric_check_passed=result.get("numeric_check_passed"),
        )

        # Update the claim in the report
        for claim in report.get("all_claims", []):
            v = claim.get("verification", {})
            if v.get("claim_id") == claim_id or claim.get("claim_text", "")[:50] == claim_id[:50]:
                claim["verification"] = new_verification.model_dump()
                break

        # Save updated report
        await save_report(job_id, symbol, report)

        return new_verification.model_dump()
    except Exception as e:
        print(f"[Route] Re-verify error: {e}")
        raise HTTPException(status_code=500, detail=f"Re-verification failed: {str(e)}")
