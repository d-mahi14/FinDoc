"""
API route for the Retriever Agent.
POST /api/retrieve — fetches, chunks, and indexes data for a company.
"""

# pyrefly: ignore [missing-import]
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.agents.retriever import run_retriever
from app.models.schemas import RetrieveResponse


router = APIRouter()


class RetrieveRequest(BaseModel):
    symbol: str
    force_refresh: bool = False


@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve_data(request: RetrieveRequest):
    """
    Fetch financial data, filings, and news for a company,
    chunk and index them in ChromaDB.
    """
    if not request.symbol or not request.symbol.strip():
        raise HTTPException(status_code=400, detail="Symbol is required")

    try:
        result = await run_retriever(
            symbol=request.symbol.strip().upper(),
            force_refresh=request.force_refresh,
        )
        return RetrieveResponse(**result)
    except Exception as e:
        print(f"[Route] Retrieve error: {e}")
        raise HTTPException(status_code=500, detail=f"Retrieval failed: {str(e)}")
