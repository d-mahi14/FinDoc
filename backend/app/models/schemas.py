"""
Pydantic models for the Financial Due-Diligence system.
Covers data source models, agent I/O, verification, and report structure.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Verdict(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"


class AgentStatusEnum(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Data Source Models
# ---------------------------------------------------------------------------

class FinancialPeriod(BaseModel):
    """A single period's financial data (annual or quarterly)."""
    period: str = Field(..., description="E.g. 'FY2024', 'Q3 FY2024', 'Mar 2024'")
    revenue: float | None = None
    net_profit: float | None = None
    operating_profit: float | None = None
    operating_cash_flow: float | None = None
    total_assets: float | None = None
    total_liabilities: float | None = None
    total_equity: float | None = None
    total_debt: float | None = None
    current_assets: float | None = None
    current_liabilities: float | None = None
    inventory: float | None = None
    gross_profit: float | None = None


class FinancialData(BaseModel):
    """Complete financial data for a company across multiple periods."""
    symbol: str
    company_name: str
    sector: str | None = None
    periods: list[FinancialPeriod] = []
    raw_tables: dict[str, Any] = Field(default_factory=dict, description="Raw parsed table data keyed by section")
    source: str = "unknown"  # "screener", "sample", "cache"
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


class Filing(BaseModel):
    """A single corporate filing or announcement."""
    date: str
    title: str
    category: str = ""
    content_text: str = ""
    url: str = ""
    source: str = "nse"


class NewsArticle(BaseModel):
    """A single news article."""
    title: str
    description: str = ""
    source_name: str = ""
    published_at: str = ""
    content: str = ""
    url: str = ""


# ---------------------------------------------------------------------------
# Chunking / Vector Store Models
# ---------------------------------------------------------------------------

class ChunkMetadata(BaseModel):
    """Metadata attached to each text chunk in the vector store."""
    source_type: str = ""         # "financials", "filing", "news"
    document_date: str = ""       # "FY2024", "2024-01-15", etc.
    section: str = ""             # "P&L", "BalanceSheet", "CashFlow", filing category, etc.
    company_symbol: str = ""
    original_source: str = ""     # URL or identifier


class Chunk(BaseModel):
    """A text chunk stored in the vector store."""
    chunk_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    text: str
    metadata: ChunkMetadata = Field(default_factory=ChunkMetadata)


# ---------------------------------------------------------------------------
# Analyst Agent Models
# ---------------------------------------------------------------------------

class ExtractedFinancials(BaseModel):
    """LLM-extracted financial figures from chunks (used as Gemini response_schema)."""
    period: str = ""
    revenue: float | None = None
    net_profit: float | None = None
    operating_profit: float | None = None
    operating_cash_flow: float | None = None
    total_debt: float | None = None
    total_equity: float | None = None
    inventory: float | None = None
    current_assets: float | None = None
    current_liabilities: float | None = None
    source_chunk_ids: list[str] = Field(default_factory=list)


class Ratio(BaseModel):
    """A computed financial ratio with source citation."""
    name: str                          # E.g. "Revenue Growth YoY"
    value: float | None = None         # The computed ratio value
    unit: str = "%"                    # "%", "x", "₹ Cr", etc.
    formula: str = ""                  # E.g. "(Rev_FY24 - Rev_FY23) / Rev_FY23 * 100"
    periods_compared: list[str] = Field(default_factory=list)
    source_chunk_ids: list[str] = Field(default_factory=list)
    interpretation: str = ""           # LLM-generated short interpretation


# ---------------------------------------------------------------------------
# Red-Flag Agent Models
# ---------------------------------------------------------------------------

class RedFlag(BaseModel):
    """A detected risk signal."""
    flag_name: str
    severity: Severity = Severity.MEDIUM
    trigger_rule: str                  # Human-readable rule description
    underlying_numbers: dict[str, Any] = Field(default_factory=dict)
    explanation: str = ""
    source_chunk_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Narrative Agent Models
# ---------------------------------------------------------------------------

class NarrativeClaim(BaseModel):
    """A single claim extracted from news/filings with source citations."""
    claim_text: str
    source_chunk_ids: list[str] = Field(default_factory=list)
    source_type: str = ""              # "news" or "filing"


class NarrativeSummary(BaseModel):
    """Complete narrative analysis output."""
    claims: list[NarrativeClaim] = Field(default_factory=list)
    overall_tone: Literal["positive", "neutral", "negative", "mixed"] = "neutral"
    summary_text: str = ""


# ---------------------------------------------------------------------------
# Verifier Agent Models
# ---------------------------------------------------------------------------

class VerificationResult(BaseModel):
    """Result of verifying a single claim."""
    claim_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    claim_text: str = ""
    verdict: Verdict = Verdict.UNSUPPORTED
    confidence: int = Field(0, ge=0, le=100)
    source_excerpt: str = ""
    explanation: str = ""
    source_chunk_ids: list[str] = Field(default_factory=list)
    numeric_check_passed: bool | None = None  # None = no numeric content to check


class ClaimWithVerification(BaseModel):
    """A claim bundled with its verification result for the final report."""
    claim_text: str
    claim_source: str = ""             # "analyst", "red_flag", "narrative"
    verification: VerificationResult = Field(default_factory=VerificationResult)


# ---------------------------------------------------------------------------
# Pipeline / Orchestration Models
# ---------------------------------------------------------------------------

class AgentStatus(BaseModel):
    """Status update for a single agent, streamed via WebSocket."""
    agent_name: str
    status: AgentStatusEnum = AgentStatusEnum.PENDING
    message: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    duration_ms: float | None = None


# ---------------------------------------------------------------------------
# Report Model
# ---------------------------------------------------------------------------

class Report(BaseModel):
    """The final compiled due-diligence report."""
    job_id: str
    symbol: str
    company_name: str = ""
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    overview: str = ""
    financial_periods: list[ExtractedFinancials] = Field(default_factory=list)
    ratios: list[Ratio] = Field(default_factory=list)
    red_flags: list[RedFlag] = Field(default_factory=list)
    narrative: NarrativeSummary = Field(default_factory=NarrativeSummary)
    all_claims: list[ClaimWithVerification] = Field(default_factory=list)
    overall_confidence: float = 0.0    # Average verification confidence
    data_sources_used: list[str] = Field(default_factory=list)
    agent_timings: list[AgentStatus] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# API Request / Response Models
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    symbol: str


class AnalyzeResponse(BaseModel):
    job_id: str
    symbol: str
    status: str = "started"


class RetrieveResponse(BaseModel):
    symbol: str
    chunks_indexed: int = 0
    financial_periods_found: int = 0
    filings_found: int = 0
    news_articles_found: int = 0
    source: str = ""


class RatiosResponse(BaseModel):
    symbol: str
    ratios: list[Ratio] = Field(default_factory=list)
    extracted_financials: list[ExtractedFinancials] = Field(default_factory=list)


class RedFlagsResponse(BaseModel):
    symbol: str
    red_flags: list[RedFlag] = Field(default_factory=list)


class NarrativeResponse(BaseModel):
    symbol: str
    narrative: NarrativeSummary = Field(default_factory=NarrativeSummary)


class VerifyRequest(BaseModel):
    claims: list[dict] = Field(default_factory=list)
    symbol: str = ""


class VerifyResponse(BaseModel):
    results: list[VerificationResult] = Field(default_factory=list)


class BenchmarkResult(BaseModel):
    """Evaluation benchmark scores."""
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_at: datetime = Field(default_factory=datetime.utcnow)
    total_claims: int = 0
    overall_accuracy: float = 0.0
    precision_supported: float = 0.0
    recall_supported: float = 0.0
    f1_supported: float = 0.0
    precision_unsupported: float = 0.0
    recall_unsupported: float = 0.0
    f1_unsupported: float = 0.0
    precision_contradicted: float = 0.0
    recall_contradicted: float = 0.0
    f1_contradicted: float = 0.0
    confusion_matrix: list[list[int]] = Field(default_factory=lambda: [[0]*3 for _ in range(3)])
    per_company: dict[str, dict] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Gemini Structured Output Schemas (used as response_schema)
# These are simpler models specifically for Gemini's structured output.
# ---------------------------------------------------------------------------

class GeminiExtractedFinancials(BaseModel):
    """Schema for Gemini to extract financial figures from chunks."""
    periods: list[ExtractedFinancials] = Field(default_factory=list)


class GeminiEntailmentResult(BaseModel):
    """Schema for Gemini entailment check."""
    verdict: Literal["SUPPORTED", "UNSUPPORTED", "CONTRADICTED"]
    confidence: int = Field(50, ge=0, le=100)
    explanation: str = ""


class GeminiRedFlagScan(BaseModel):
    """Schema for Gemini to scan text for exceptional items / red flags."""
    mentions: list[str] = Field(default_factory=list, description="Exact text excerpts mentioning exceptional items, write-offs, impairments, one-time charges")
    count: int = 0


class GeminiNarrativeExtraction(BaseModel):
    """Schema for Gemini to extract narrative claims from text."""
    claims: list[NarrativeClaim] = Field(default_factory=list)
    overall_tone: Literal["positive", "neutral", "negative", "mixed"] = "neutral"


class GeminiRatioInterpretation(BaseModel):
    """Schema for Gemini to interpret computed ratios."""
    interpretation: str = ""
    key_highlights: list[str] = Field(default_factory=list)
