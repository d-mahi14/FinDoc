"""
API routes for analysis — ratios, red flags, narrative, full pipeline, and report retrieval.
Also includes the WebSocket endpoint for live pipeline streaming.
"""

import asyncio
import uuid

# pyrefly: ignore [missing-import]
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from pydantic import BaseModel

from app.agents.analyst import run_analyst
from app.agents.red_flag import run_red_flag_agent
from app.agents.narrative import run_narrative_agent
from app.agents.orchestrator import run_pipeline
from app.models.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    RatiosResponse,
    RedFlagsResponse,
    NarrativeResponse,
)
from app.utils.db import get_report
from app.utils.ws_manager import ws_manager


router = APIRouter()


# ---------------------------------------------------------------------------
# Individual Agent Endpoints
# ---------------------------------------------------------------------------

class SymbolRequest(BaseModel):
    symbol: str


@router.post("/analyze/ratios", response_model=RatiosResponse)
async def analyze_ratios(request: SymbolRequest):
    """Run the Analyst Agent to extract financials and compute ratios."""
    if not request.symbol or not request.symbol.strip():
        raise HTTPException(status_code=400, detail="Symbol is required")

    try:
        result = await run_analyst(request.symbol.strip().upper())
        return RatiosResponse(**result)
    except Exception as e:
        print(f"[Route] Analyst error: {e}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@router.post("/analyze/redflags", response_model=RedFlagsResponse)
async def analyze_red_flags(request: SymbolRequest):
    """Run the Red-Flag Agent to detect risk signals."""
    if not request.symbol or not request.symbol.strip():
        raise HTTPException(status_code=400, detail="Symbol is required")

    try:
        result = await run_red_flag_agent(request.symbol.strip().upper())
        return RedFlagsResponse(**result)
    except Exception as e:
        print(f"[Route] Red-Flag error: {e}")
        raise HTTPException(status_code=500, detail=f"Red-flag analysis failed: {str(e)}")


@router.post("/analyze/narrative", response_model=NarrativeResponse)
async def analyze_narrative(request: SymbolRequest):
    """Run the Narrative Agent to extract narrative claims from news/filings."""
    if not request.symbol or not request.symbol.strip():
        raise HTTPException(status_code=400, detail="Symbol is required")

    try:
        result = await run_narrative_agent(request.symbol.strip().upper())
        return NarrativeResponse(**result)
    except Exception as e:
        print(f"[Route] Narrative error: {e}")
        raise HTTPException(status_code=500, detail=f"Narrative analysis failed: {str(e)}")


# ---------------------------------------------------------------------------
# Full Pipeline
# ---------------------------------------------------------------------------

# In-memory job tracking (for demo; production would use Redis/DB)
_active_jobs: dict[str, dict] = {}


@router.post("/analyze", response_model=AnalyzeResponse)
async def start_analysis(request: AnalyzeRequest, background_tasks: BackgroundTasks):
    """
    Start the full due-diligence pipeline.
    Returns immediately with a job_id. Connect to WS /ws/analyze/{job_id} for live updates.
    """
    if not request.symbol or not request.symbol.strip():
        raise HTTPException(status_code=400, detail="Symbol is required")

    symbol = request.symbol.strip().upper()
    job_id = str(uuid.uuid4())

    _active_jobs[job_id] = {"symbol": symbol, "status": "started"}

    # Run pipeline in the background
    background_tasks.add_task(_run_pipeline_background, symbol, job_id)

    return AnalyzeResponse(job_id=job_id, symbol=symbol, status="started")


async def _run_pipeline_background(symbol: str, job_id: str):
    """Background task wrapper for the pipeline."""
    try:
        _active_jobs[job_id]["status"] = "running"
        result = await run_pipeline(symbol, job_id)
        _active_jobs[job_id]["status"] = "complete"
        _active_jobs[job_id]["result"] = result
    except Exception as e:
        print(f"[Route] Pipeline error for job {job_id}: {e}")
        _active_jobs[job_id]["status"] = "error"
        _active_jobs[job_id]["error"] = str(e)
        await ws_manager.send_error(job_id, str(e))


# ---------------------------------------------------------------------------
# Report Retrieval
# ---------------------------------------------------------------------------

@router.get("/report/{job_id}")
async def get_report_by_id(job_id: str):
    """Get the completed report for a job."""
    report = await get_report(job_id)
    if report:
        return report

    # Check if job is still running
    if job_id in _active_jobs:
        status = _active_jobs[job_id].get("status", "unknown")
        if status in ("started", "running"):
            return {"status": "in_progress", "job_id": job_id, "message": "Analysis still running..."}
        elif status == "error":
            raise HTTPException(
                status_code=500,
                detail=f"Analysis failed: {_active_jobs[job_id].get('error', 'unknown')}"
            )

    raise HTTPException(status_code=404, detail=f"Report not found for job {job_id}")


@router.get("/job/{job_id}/status")
async def get_job_status(job_id: str):
    """Get the current status of a pipeline job."""
    if job_id in _active_jobs:
        return {
            "job_id": job_id,
            "status": _active_jobs[job_id].get("status", "unknown"),
            "symbol": _active_jobs[job_id].get("symbol", ""),
        }
    # Check if report exists (completed job)
    report = await get_report(job_id)
    if report:
        return {"job_id": job_id, "status": "complete", "symbol": report.get("symbol", "")}

    raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
