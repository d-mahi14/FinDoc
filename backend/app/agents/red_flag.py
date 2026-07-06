"""
Red-Flag Agent — rule-based + LLM hybrid risk detection.

Detects financial red flags using deterministic Python rules for ratio-based
signals and Gemini structured output for text-based signals (exceptional items).
"""

import time
from typing import Any

from app.models.schemas import (
    RedFlag,
    Severity,
    RedFlagsResponse,
    ExtractedFinancials,
    GeminiRedFlagScan,
)
from app.utils.llm_client import get_llm_client
from app.utils.vector_store import query_chunks
from app.utils.db import log_llm_usage


async def run_red_flag_agent(symbol: str, extracted_financials: list[dict] = None) -> dict:
    """
    Main entry point for the Red-Flag Agent.

    1. Takes extracted financials (from Analyst) or queries ChromaDB
    2. Applies rule-based detection for ratio-based red flags
    3. Uses LLM to scan for exceptional item mentions
    4. Returns flagged risks with severity, trigger rule, and underlying numbers

    Returns a dict with red_flags list.
    """
    symbol = symbol.upper().strip()
    start_time = time.time()
    print(f"[RedFlag] Starting red-flag analysis for {symbol}...")

    llm = get_llm_client()

    # Parse extracted financials
    periods = []
    if extracted_financials:
        for ef in extracted_financials:
            if isinstance(ef, dict):
                periods.append(ExtractedFinancials.model_validate(ef))
            else:
                periods.append(ef)

    # If no extracted financials provided, query ChromaDB and parse
    if not periods:
        chunks = query_chunks(
            company_symbol=symbol,
            query="revenue profit cash flow debt equity financial summary",
            n_results=15,
            source_type="financials",
        )
        # We'll work with whatever ratio data we can get from chunks
        print(f"[RedFlag] Using {len(chunks)} financial chunks directly")

    # Sort periods most recent first
    sorted_periods = sorted(periods, key=lambda p: p.period, reverse=True)

    # -----------------------------------------------------------------------
    # Rule-based Red Flag Detection
    # -----------------------------------------------------------------------
    red_flags: list[RedFlag] = []

    # Flag 1: Revenue up while operating cash flow down
    flag = _check_revenue_vs_cashflow(sorted_periods)
    if flag:
        red_flags.append(flag)

    # Flag 2: Inventory growing faster than revenue
    flag = _check_inventory_vs_revenue(sorted_periods)
    if flag:
        red_flags.append(flag)

    # Flag 3: Rising debt-to-equity across consecutive periods
    flag = _check_rising_debt_equity(sorted_periods)
    if flag:
        red_flags.append(flag)

    # Flag 4: Margin compression across 2+ periods
    flags = _check_margin_compression(sorted_periods)
    red_flags.extend(flags)

    # -----------------------------------------------------------------------
    # LLM-based: Scan for exceptional items in filings
    # -----------------------------------------------------------------------
    if llm.is_configured():
        exceptional_flags = await _scan_exceptional_items(llm, symbol)
        red_flags.extend(exceptional_flags)

    duration_ms = (time.time() - start_time) * 1000
    await log_llm_usage(
        agent_name="red_flag",
        model="aggregate",
        latency_ms=duration_ms,
        symbol=symbol,
    )

    result = {
        "symbol": symbol,
        "red_flags": [rf.model_dump() for rf in red_flags],
    }

    print(f"[RedFlag] Completed for {symbol}: {len(red_flags)} flags detected "
          f"in {duration_ms:.0f}ms")

    return result


# ---------------------------------------------------------------------------
# Rule-based detection functions
# ---------------------------------------------------------------------------

def _check_revenue_vs_cashflow(periods: list[ExtractedFinancials]) -> RedFlag | None:
    """Flag: Revenue increasing while operating cash flow is decreasing."""
    if len(periods) < 2:
        return None

    for i in range(len(periods) - 1):
        curr, prev = periods[i], periods[i + 1]

        if (curr.revenue is not None and prev.revenue is not None and
            curr.operating_cash_flow is not None and prev.operating_cash_flow is not None):

            rev_growth = curr.revenue - prev.revenue
            ocf_change = curr.operating_cash_flow - prev.operating_cash_flow

            if rev_growth > 0 and ocf_change < 0:
                return RedFlag(
                    flag_name="Revenue-Cash Flow Divergence",
                    severity=Severity.HIGH,
                    trigger_rule="Revenue increased while operating cash flow decreased — may indicate aggressive revenue recognition or deteriorating cash conversion.",
                    underlying_numbers={
                        "revenue_current": curr.revenue,
                        "revenue_previous": prev.revenue,
                        "revenue_change": round(rev_growth, 2),
                        "ocf_current": curr.operating_cash_flow,
                        "ocf_previous": prev.operating_cash_flow,
                        "ocf_change": round(ocf_change, 2),
                        "periods": f"{curr.period} vs {prev.period}",
                    },
                    explanation=(
                        f"Revenue grew by ₹{rev_growth:,.0f} Cr ({curr.period} vs {prev.period}), "
                        f"but operating cash flow declined by ₹{abs(ocf_change):,.0f} Cr. "
                        f"This divergence warrants investigation into cash conversion quality."
                    ),
                )
    return None


def _check_inventory_vs_revenue(periods: list[ExtractedFinancials]) -> RedFlag | None:
    """Flag: Inventory growing faster than revenue."""
    if len(periods) < 2:
        return None

    for i in range(len(periods) - 1):
        curr, prev = periods[i], periods[i + 1]

        if (curr.inventory is not None and prev.inventory is not None and
            curr.revenue is not None and prev.revenue is not None and
            prev.inventory > 0 and prev.revenue > 0):

            inv_growth_pct = ((curr.inventory - prev.inventory) / prev.inventory) * 100
            rev_growth_pct = ((curr.revenue - prev.revenue) / prev.revenue) * 100

            if inv_growth_pct > rev_growth_pct and inv_growth_pct > 5:
                return RedFlag(
                    flag_name="Inventory Buildup",
                    severity=Severity.MEDIUM if inv_growth_pct - rev_growth_pct < 15 else Severity.HIGH,
                    trigger_rule="Inventory growing faster than revenue — may indicate slowing demand or potential write-down risk.",
                    underlying_numbers={
                        "inventory_growth_pct": round(inv_growth_pct, 2),
                        "revenue_growth_pct": round(rev_growth_pct, 2),
                        "gap_pct": round(inv_growth_pct - rev_growth_pct, 2),
                        "inventory_current": curr.inventory,
                        "inventory_previous": prev.inventory,
                        "periods": f"{curr.period} vs {prev.period}",
                    },
                    explanation=(
                        f"Inventory grew {inv_growth_pct:.1f}% while revenue grew {rev_growth_pct:.1f}% "
                        f"({curr.period} vs {prev.period}). The {inv_growth_pct - rev_growth_pct:.1f}pp gap "
                        f"suggests potential demand slowdown or channel stuffing."
                    ),
                )
    return None


def _check_rising_debt_equity(periods: list[ExtractedFinancials]) -> RedFlag | None:
    """Flag: Rising debt-to-equity across consecutive periods."""
    if len(periods) < 3:
        return None

    de_ratios = []
    for p in periods:
        if p.total_debt is not None and p.total_equity is not None and p.total_equity > 0:
            de_ratios.append((p.period, p.total_debt / p.total_equity))

    if len(de_ratios) < 3:
        return None

    # Check if D/E is rising across 3+ consecutive periods (periods are reverse chronological)
    # So rising means later periods (earlier dates) have lower D/E
    rising_count = 0
    for i in range(len(de_ratios) - 1):
        if de_ratios[i][1] > de_ratios[i + 1][1]:  # More recent > older
            rising_count += 1

    if rising_count >= 2:
        return RedFlag(
            flag_name="Rising Debt-to-Equity",
            severity=Severity.MEDIUM if de_ratios[0][1] < 1.0 else Severity.HIGH,
            trigger_rule="Debt-to-equity ratio has been rising across 3+ consecutive periods — increasing financial leverage.",
            underlying_numbers={
                "de_ratios": {period: round(de, 4) for period, de in de_ratios},
                "current_de": round(de_ratios[0][1], 4),
                "trend_periods": rising_count + 1,
            },
            explanation=(
                f"Debt-to-equity has risen across {rising_count + 1} consecutive periods, "
                f"from {de_ratios[-1][1]:.4f}x ({de_ratios[-1][0]}) to "
                f"{de_ratios[0][1]:.4f}x ({de_ratios[0][0]}). "
                f"Increasing leverage may indicate higher financial risk."
            ),
        )
    return None


def _check_margin_compression(periods: list[ExtractedFinancials]) -> list[RedFlag]:
    """Flag: Margin compression across 2+ consecutive periods."""
    flags = []

    if len(periods) < 3:
        return flags

    # Check operating margin
    op_margins = []
    for p in periods:
        if p.revenue is not None and p.operating_profit is not None and p.revenue > 0:
            op_margins.append((p.period, (p.operating_profit / p.revenue) * 100))

    if len(op_margins) >= 3:
        declining = 0
        for i in range(len(op_margins) - 1):
            if op_margins[i][1] < op_margins[i + 1][1]:
                declining += 1

        if declining >= 2:
            flags.append(RedFlag(
                flag_name="Operating Margin Compression",
                severity=Severity.MEDIUM,
                trigger_rule="Operating margin has declined across 2+ consecutive periods — may indicate pricing pressure or rising costs.",
                underlying_numbers={
                    "margins": {period: round(m, 2) for period, m in op_margins},
                    "decline_periods": declining,
                    "total_compression_pp": round(op_margins[-1][1] - op_margins[0][1], 2),
                },
                explanation=(
                    f"Operating margin compressed from {op_margins[-1][1]:.1f}% ({op_margins[-1][0]}) "
                    f"to {op_margins[0][1]:.1f}% ({op_margins[0][0]}), declining across "
                    f"{declining} consecutive periods. This suggests either pricing pressure "
                    f"or rising input costs."
                ),
            ))

    # Check net profit margin
    np_margins = []
    for p in periods:
        if p.revenue is not None and p.net_profit is not None and p.revenue > 0:
            np_margins.append((p.period, (p.net_profit / p.revenue) * 100))

    if len(np_margins) >= 3:
        declining = 0
        for i in range(len(np_margins) - 1):
            if np_margins[i][1] < np_margins[i + 1][1]:
                declining += 1

        if declining >= 2:
            flags.append(RedFlag(
                flag_name="Net Margin Compression",
                severity=Severity.MEDIUM,
                trigger_rule="Net profit margin has declined across 2+ consecutive periods.",
                underlying_numbers={
                    "margins": {period: round(m, 2) for period, m in np_margins},
                    "decline_periods": declining,
                },
                explanation=(
                    f"Net profit margin moved from {np_margins[-1][1]:.1f}% ({np_margins[-1][0]}) "
                    f"to {np_margins[0][1]:.1f}% ({np_margins[0][0]}), declining across "
                    f"{declining} consecutive periods."
                ),
            ))

    return flags


# ---------------------------------------------------------------------------
# LLM-based detection
# ---------------------------------------------------------------------------

async def _scan_exceptional_items(llm, symbol: str) -> list[RedFlag]:
    """Use LLM to scan filings for exceptional item charges."""
    flags = []

    # Query filing chunks for exceptional items
    chunks = query_chunks(
        company_symbol=symbol,
        query="exceptional item write-off impairment one-time charge extraordinary loss write-down",
        n_results=10,
        source_type="filing",
    )

    if not chunks:
        return flags

    chunks_text = "\n\n---\n\n".join([c.get("text", "") for c in chunks])
    chunk_ids = [c["chunk_id"] for c in chunks]

    try:
        result = llm.generate_structured(
            message=f"""Scan the following corporate filings/announcements for mentions of:
- Exceptional items or charges
- One-time write-offs or impairments
- Extraordinary losses or gains
- Asset write-downs

Extract exact text excerpts that mention these items.

FILINGS TEXT:
{chunks_text}""",
            response_schema=GeminiRedFlagScan,
            agent_name="red_flag_scanner",
            system_instruction="Extract exact text excerpts mentioning exceptional items, write-offs, impairments, or one-time charges.",
        )

        if result and result.count and result.count >= 2:
            flags.append(RedFlag(
                flag_name="Frequent Exceptional Items",
                severity=Severity.MEDIUM if result.count < 4 else Severity.HIGH,
                trigger_rule=f"Found {result.count} mentions of exceptional items/write-offs across filings — frequent one-time charges may indicate recurring issues.",
                underlying_numbers={
                    "mention_count": result.count,
                    "mentions": result.mentions[:5],  # Limit to 5
                },
                explanation=(
                    f"Detected {result.count} references to exceptional items or write-offs "
                    f"in recent filings. Frequent 'one-time' charges that recur regularly "
                    f"may indicate underlying structural issues."
                ),
                source_chunk_ids=chunk_ids,
            ))

    except Exception as e:
        print(f"[RedFlag] LLM exceptional items scan failed: {e}")

    return flags
