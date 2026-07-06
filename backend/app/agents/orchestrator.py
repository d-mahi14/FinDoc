"""
LangGraph Orchestrator — wires the full agent pipeline as a state machine.

Pipeline: Retriever → [Analyst, Red-Flag, Sentiment] (parallel after Retriever) → Critic → Report Generator

Streams status updates via WebSocket for each agent step.
"""

import asyncio
import time
import uuid
from typing import Any, TypedDict

from app.agents.retriever import run_retriever
from app.agents.analyst import run_analyst
from app.agents.red_flag import run_red_flag_agent
from app.agents.narrative import run_narrative_agent
from app.agents.verifier import run_verifier
from app.agents.report_generator import run_report_generator
from app.utils.ws_manager import ws_manager
from app.utils.db import log_llm_usage


# ---------------------------------------------------------------------------
# Pipeline State
# ---------------------------------------------------------------------------

class PipelineState(TypedDict, total=False):
    symbol: str
    job_id: str
    # Retriever output
    retriever_result: dict
    company_name: str
    # Analyst output
    extracted_financials: list
    ratios: list
    # Red-Flag output
    red_flags: list
    # Narrative output
    narrative: dict
    # All claims for verification
    all_claims_for_verification: list
    # Verification results
    verification_results: list
    # Final report
    report: dict
    # Metadata
    data_sources: list
    agent_timings: list
    errors: list


# ---------------------------------------------------------------------------
# Pipeline Execution
# ---------------------------------------------------------------------------

async def run_pipeline(symbol: str, job_id: str) -> dict:
    """
    Execute the full due-diligence pipeline.

    Flow:
    1. Retriever (fetch + chunk + embed)
    2. Analyst + Red-Flag + Narrative (parallel)
    3. Verifier (verify all claims)
    4. Report Generator (compile final report)

    Streams status via WebSocket throughout.
    """
    symbol = symbol.upper().strip()
    pipeline_start = time.time()
    print(f"[Orchestrator] Starting pipeline for {symbol} (job: {job_id})")

    state: PipelineState = {
        "symbol": symbol,
        "job_id": job_id,
        "agent_timings": [],
        "errors": [],
        "data_sources": [],
    }

    # ===================================================================
    # STEP 1: Retriever
    # ===================================================================
    await ws_manager.send_agent_status(job_id, "retriever", "in_progress", "Fetching and indexing data...")

    try:
        step_start = time.time()
        result = await run_retriever(symbol)
        duration = (time.time() - step_start) * 1000

        state["retriever_result"] = result
        state["company_name"] = result.get("company_name", symbol)
        state["data_sources"].append(result.get("source", "unknown"))

        state["agent_timings"].append({
            "agent_name": "retriever",
            "status": "complete",
            "message": f"Indexed {result.get('chunks_indexed', 0)} chunks",
            "duration_ms": round(duration, 1),
        })

        await ws_manager.send_agent_status(
            job_id, "retriever", "complete",
            f"Indexed {result.get('chunks_indexed', 0)} chunks from {result.get('source', 'unknown')}",
            duration_ms=round(duration, 1),
        )
    except Exception as e:
        state["errors"].append(f"Retriever: {str(e)}")
        state["agent_timings"].append({
            "agent_name": "retriever", "status": "error", "message": str(e),
        })
        await ws_manager.send_agent_status(job_id, "retriever", "error", str(e))
        await ws_manager.send_error(job_id, f"Retriever failed: {e}", "retriever")
        # Can't continue without data
        return state

    # ===================================================================
    # STEP 2: Analyst + Red-Flag + Narrative (parallel)
    # ===================================================================
    await ws_manager.send_agent_status(job_id, "analyst", "in_progress", "Extracting financials and computing ratios...")
    await ws_manager.send_agent_status(job_id, "red_flag", "in_progress", "Scanning for risk signals...")
    await ws_manager.send_agent_status(job_id, "narrative", "in_progress", "Analyzing news and filings...")

    # Run in parallel
    analyst_task = asyncio.create_task(_run_agent_safe("analyst", run_analyst, symbol))
    redflag_task = asyncio.create_task(_run_agent_safe("red_flag", run_red_flag_agent, symbol))
    narrative_task = asyncio.create_task(_run_agent_safe("narrative", run_narrative_agent, symbol))

    analyst_result, redflag_result, narrative_result = await asyncio.gather(
        analyst_task, redflag_task, narrative_task
    )

    # Process Analyst result
    if analyst_result.get("success"):
        data = analyst_result["data"]
        state["extracted_financials"] = data.get("extracted_financials", [])
        state["ratios"] = data.get("ratios", [])

        state["agent_timings"].append({
            "agent_name": "analyst", "status": "complete",
            "message": f"{len(state['ratios'])} ratios computed",
            "duration_ms": analyst_result.get("duration_ms", 0),
        })
        await ws_manager.send_agent_status(
            job_id, "analyst", "complete",
            f"Computed {len(state['ratios'])} ratios from {len(state['extracted_financials'])} periods",
            duration_ms=analyst_result.get("duration_ms"),
        )

        # Now run red-flag with extracted financials if we have them
        # (Re-run if we didn't have financials before)
        if state["extracted_financials"] and not redflag_result.get("data", {}).get("red_flags"):
            redflag_result = await _run_agent_safe(
                "red_flag",
                lambda s: run_red_flag_agent(s, extracted_financials=state["extracted_financials"]),
                symbol,
            )
    else:
        state["errors"].append(f"Analyst: {analyst_result.get('error', 'unknown')}")
        state["agent_timings"].append({
            "agent_name": "analyst", "status": "error",
            "message": analyst_result.get("error", "unknown"),
        })
        await ws_manager.send_agent_status(
            job_id, "analyst", "error", analyst_result.get("error", "unknown")
        )

    # Process Red-Flag result
    if redflag_result.get("success"):
        data = redflag_result["data"]
        state["red_flags"] = data.get("red_flags", [])

        state["agent_timings"].append({
            "agent_name": "red_flag", "status": "complete",
            "message": f"{len(state['red_flags'])} flags detected",
            "duration_ms": redflag_result.get("duration_ms", 0),
        })
        await ws_manager.send_agent_status(
            job_id, "red_flag", "complete",
            f"Detected {len(state['red_flags'])} red flags",
            duration_ms=redflag_result.get("duration_ms"),
        )
    else:
        state["errors"].append(f"Red-Flag: {redflag_result.get('error', 'unknown')}")
        state["agent_timings"].append({
            "agent_name": "red_flag", "status": "error",
            "message": redflag_result.get("error", "unknown"),
        })
        await ws_manager.send_agent_status(
            job_id, "red_flag", "error", redflag_result.get("error", "unknown")
        )

    # Process Narrative result
    if narrative_result.get("success"):
        data = narrative_result["data"]
        state["narrative"] = data.get("narrative", {})

        claim_count = len(state["narrative"].get("claims", []))
        state["agent_timings"].append({
            "agent_name": "narrative", "status": "complete",
            "message": f"{claim_count} narrative claims extracted",
            "duration_ms": narrative_result.get("duration_ms", 0),
        })
        await ws_manager.send_agent_status(
            job_id, "narrative", "complete",
            f"Extracted {claim_count} narrative claims, tone: {state['narrative'].get('overall_tone', 'neutral')}",
            duration_ms=narrative_result.get("duration_ms"),
        )
    else:
        state["errors"].append(f"Narrative: {narrative_result.get('error', 'unknown')}")
        state["agent_timings"].append({
            "agent_name": "narrative", "status": "error",
            "message": narrative_result.get("error", "unknown"),
        })
        await ws_manager.send_agent_status(
            job_id, "narrative", "error", narrative_result.get("error", "unknown")
        )

    # ===================================================================
    # STEP 3: Verifier (verify all claims from previous agents)
    # ===================================================================
    await ws_manager.send_agent_status(job_id, "verifier", "in_progress", "Verifying all claims...")

    # Collect all claims for verification
    all_claims = []

    # From ratios
    for ratio in state.get("ratios", []):
        claim_text = f"{ratio.get('name', '')}: {ratio.get('value', 'N/A')}{ratio.get('unit', '')}"
        all_claims.append({
            "claim_text": claim_text,
            "source_chunk_ids": ratio.get("source_chunk_ids", []),
            "claim_source": "analyst",
        })

    # From red flags
    for rf in state.get("red_flags", []):
        all_claims.append({
            "claim_text": rf.get("explanation", rf.get("flag_name", "")),
            "source_chunk_ids": rf.get("source_chunk_ids", []),
            "claim_source": "red_flag",
        })

    # From narrative
    for nc in state.get("narrative", {}).get("claims", []):
        all_claims.append({
            "claim_text": nc.get("claim_text", "") if isinstance(nc, dict) else nc.claim_text,
            "source_chunk_ids": nc.get("source_chunk_ids", []) if isinstance(nc, dict) else nc.source_chunk_ids,
            "claim_source": "narrative",
        })

    state["all_claims_for_verification"] = all_claims

    try:
        step_start = time.time()
        verification_results = await run_verifier(all_claims, symbol)
        duration = (time.time() - step_start) * 1000

        state["verification_results"] = verification_results

        supported = sum(1 for v in verification_results if v.get("verdict") == "SUPPORTED")
        total = len(verification_results)

        state["agent_timings"].append({
            "agent_name": "verifier", "status": "complete",
            "message": f"Verified {total} claims ({supported} supported)",
            "duration_ms": round(duration, 1),
        })
        await ws_manager.send_agent_status(
            job_id, "verifier", "complete",
            f"Verified {total} claims: {supported} supported",
            duration_ms=round(duration, 1),
        )
    except Exception as e:
        state["errors"].append(f"Verifier: {str(e)}")
        state["verification_results"] = []
        state["agent_timings"].append({
            "agent_name": "verifier", "status": "error", "message": str(e),
        })
        await ws_manager.send_agent_status(job_id, "verifier", "error", str(e))

    # ===================================================================
    # STEP 4: Report Generator
    # ===================================================================
    await ws_manager.send_agent_status(job_id, "report_generator", "in_progress", "Compiling final report...")

    try:
        step_start = time.time()
        report = await run_report_generator(
            symbol=symbol,
            job_id=job_id,
            company_name=state.get("company_name", symbol),
            extracted_financials=state.get("extracted_financials", []),
            ratios=state.get("ratios", []),
            red_flags=state.get("red_flags", []),
            narrative=state.get("narrative"),
            verification_results=state.get("verification_results", []),
            agent_timings=state.get("agent_timings", []),
            data_sources=state.get("data_sources", []),
        )
        duration = (time.time() - step_start) * 1000

        state["report"] = report

        state["agent_timings"].append({
            "agent_name": "report_generator", "status": "complete",
            "message": f"Report compiled with confidence {report.get('overall_confidence', 0):.1f}%",
            "duration_ms": round(duration, 1),
        })
        await ws_manager.send_agent_status(
            job_id, "report_generator", "complete",
            f"Report ready — confidence: {report.get('overall_confidence', 0):.1f}%",
            duration_ms=round(duration, 1),
        )
    except Exception as e:
        state["errors"].append(f"Report Generator: {str(e)}")
        state["agent_timings"].append({
            "agent_name": "report_generator", "status": "error", "message": str(e),
        })
        await ws_manager.send_agent_status(job_id, "report_generator", "error", str(e))

    # ===================================================================
    # Pipeline Complete
    # ===================================================================
    total_duration = (time.time() - pipeline_start) * 1000
    print(f"[Orchestrator] Pipeline complete for {symbol} in {total_duration:.0f}ms "
          f"({len(state.get('errors', []))} errors)")

    await ws_manager.send_pipeline_complete(
        job_id, report_available=bool(state.get("report"))
    )

    return state


async def _run_agent_safe(agent_name: str, agent_fn, *args) -> dict:
    """Run an agent with error handling, returning a standardized result."""
    try:
        step_start = time.time()
        result = await agent_fn(*args)
        duration_ms = (time.time() - step_start) * 1000
        return {"success": True, "data": result, "duration_ms": round(duration_ms, 1)}
    except Exception as e:
        print(f"[Orchestrator] {agent_name} failed: {e}")
        return {"success": False, "error": str(e), "data": {}}
