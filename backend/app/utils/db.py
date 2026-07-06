"""
SQLite async database manager for caching, reports, and usage logging.
Uses aiosqlite for non-blocking I/O within FastAPI's async event loop.
"""

import json
import os
import time
from datetime import datetime, timedelta
from typing import Any

# pyrefly: ignore [missing-import]
import aiosqlite

# Database file lives alongside the backend app
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "findocs.db")

_db_initialized = False


async def get_db() -> aiosqlite.Connection:
    """Get a database connection."""
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


async def init_db():
    """Create all tables if they don't exist. Called once at startup."""
    global _db_initialized
    if _db_initialized:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        # Cached financial data from Screener.in
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cached_financials (
                symbol TEXT PRIMARY KEY,
                data_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                source TEXT DEFAULT 'live',
                ttl_hours INTEGER DEFAULT 24
            )
        """)

        # Cached NSE filings/announcements
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cached_filings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                data_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                source TEXT DEFAULT 'live',
                ttl_hours INTEGER DEFAULT 24,
                UNIQUE(symbol)
            )
        """)

        # Cached news articles
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cached_news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                data_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                source TEXT DEFAULT 'live',
                ttl_hours INTEGER DEFAULT 12,
                UNIQUE(symbol)
            )
        """)

        # Analysis reports
        await db.execute("""
            CREATE TABLE IF NOT EXISTS analysis_reports (
                job_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                report_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT DEFAULT 'complete'
            )
        """)

        # LLM usage logging (token counts + latency)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS llm_usage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                model TEXT NOT NULL,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                latency_ms REAL DEFAULT 0,
                timestamp TEXT NOT NULL,
                symbol TEXT DEFAULT '',
                job_id TEXT DEFAULT ''
            )
        """)

        # Benchmark evaluation results
        await db.execute("""
            CREATE TABLE IF NOT EXISTS benchmark_results (
                run_id TEXT PRIMARY KEY,
                result_json TEXT NOT NULL,
                run_at TEXT NOT NULL
            )
        """)

        await db.commit()

    _db_initialized = True
    print(f"[DB] SQLite initialized at {DB_PATH}")


# ---------------------------------------------------------------------------
# Generic cache helpers
# ---------------------------------------------------------------------------

async def cache_get(table: str, symbol: str) -> dict | None:
    """
    Retrieve cached data for a symbol if it exists and hasn't expired.
    Returns the parsed JSON data or None.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT data_json, fetched_at, ttl_hours FROM {table} WHERE symbol = ?",
            (symbol.upper(),)
        )
        row = await cursor.fetchone()

        if row is None:
            return None

        # Check TTL
        fetched_at = datetime.fromisoformat(row["fetched_at"])
        ttl = row["ttl_hours"] if row["ttl_hours"] else 24
        if datetime.utcnow() - fetched_at > timedelta(hours=ttl):
            return None  # Expired

        try:
            return json.loads(row["data_json"])
        except json.JSONDecodeError:
            return None


async def cache_set(table: str, symbol: str, data: Any, ttl_hours: int = 24, source: str = "live"):
    """Store data in the cache table, upserting by symbol."""
    data_json = json.dumps(data, default=str)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"""INSERT INTO {table} (symbol, data_json, fetched_at, source, ttl_hours)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    data_json = excluded.data_json,
                    fetched_at = excluded.fetched_at,
                    source = excluded.source,
                    ttl_hours = excluded.ttl_hours
            """,
            (symbol.upper(), data_json, datetime.utcnow().isoformat(), source, ttl_hours)
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Report persistence
# ---------------------------------------------------------------------------

async def save_report(job_id: str, symbol: str, report_data: dict):
    """Save a completed analysis report."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO analysis_reports (job_id, symbol, report_json, created_at, status)
               VALUES (?, ?, ?, ?, 'complete')""",
            (job_id, symbol.upper(), json.dumps(report_data, default=str), datetime.utcnow().isoformat())
        )
        await db.commit()


async def get_report(job_id: str) -> dict | None:
    """Retrieve a report by job_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT report_json FROM analysis_reports WHERE job_id = ?",
            (job_id,)
        )
        row = await cursor.fetchone()
        if row:
            return json.loads(row["report_json"])
        return None


# ---------------------------------------------------------------------------
# LLM usage logging
# ---------------------------------------------------------------------------

async def log_llm_usage(
    agent_name: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    latency_ms: float = 0,
    symbol: str = "",
    job_id: str = ""
):
    """Log a single LLM API call for monitoring."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO llm_usage_log
               (agent_name, model, input_tokens, output_tokens, latency_ms, timestamp, symbol, job_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (agent_name, model, input_tokens, output_tokens, latency_ms,
             datetime.utcnow().isoformat(), symbol, job_id)
        )
        await db.commit()


async def get_usage_stats() -> dict:
    """Get aggregate LLM usage statistics."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT
                agent_name,
                COUNT(*) as call_count,
                SUM(input_tokens) as total_input_tokens,
                SUM(output_tokens) as total_output_tokens,
                AVG(latency_ms) as avg_latency_ms
            FROM llm_usage_log
            GROUP BY agent_name
        """)
        rows = await cursor.fetchall()
        return {row["agent_name"]: dict(row) for row in rows}


# ---------------------------------------------------------------------------
# Benchmark results
# ---------------------------------------------------------------------------

async def save_benchmark_result(run_id: str, result_data: dict):
    """Save benchmark evaluation results."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO benchmark_results (run_id, result_json, run_at)
               VALUES (?, ?, ?)""",
            (run_id, json.dumps(result_data, default=str), datetime.utcnow().isoformat())
        )
        await db.commit()


async def get_latest_benchmark() -> dict | None:
    """Get the most recent benchmark result."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT result_json FROM benchmark_results ORDER BY run_at DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        if row:
            return json.loads(row["result_json"])
        return None
