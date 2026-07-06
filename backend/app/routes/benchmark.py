"""
API route for benchmark evaluation results.
GET /api/benchmark/results — returns the latest benchmark scores.
"""

# pyrefly: ignore [missing-import]
from fastapi import APIRouter, HTTPException

from app.utils.db import get_latest_benchmark


router = APIRouter()


@router.get("/benchmark/results")
async def get_benchmark_results():
    """Get the latest benchmark evaluation results."""
    result = await get_latest_benchmark()
    if not result:
        raise HTTPException(
            status_code=404,
            detail="No benchmark results found. Run 'py -3 benchmark/run_eval.py' first."
        )
    return result
