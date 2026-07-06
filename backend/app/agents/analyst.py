"""
Analyst Agent — extracts financial figures from indexed chunks via Gemini structured output,
then computes ratios deterministically in Python. Every ratio carries source citations.

Key principle: LLM locates numbers; Python does all math.
"""

import time
from typing import Any

from app.models.schemas import (
    ExtractedFinancials,
    Ratio,
    RatiosResponse,
    GeminiExtractedFinancials,
    GeminiRatioInterpretation,
)
from app.utils.llm_client import get_llm_client
from app.utils.vector_store import query_chunks
from app.utils.db import log_llm_usage


async def run_analyst(symbol: str) -> dict:
    """
    Main entry point for the Analyst Agent.

    1. Query ChromaDB for financial data chunks
    2. Use Gemini structured output to extract raw figures
    3. Compute ratios deterministically in Python
    4. Generate short LLM interpretation for each ratio

    Returns a dict with extracted_financials and ratios.
    """
    symbol = symbol.upper().strip()
    start_time = time.time()
    print(f"[Analyst] Starting analysis for {symbol}...")

    llm = get_llm_client()

    # -----------------------------------------------------------------------
    # Step 1: Retrieve relevant financial chunks
    # -----------------------------------------------------------------------
    financial_chunks = query_chunks(
        company_symbol=symbol,
        query="revenue net profit operating profit cash flow debt equity financial results",
        n_results=20,
        source_type="financials",
    )

    if not financial_chunks:
        print(f"[Analyst] No financial chunks found for {symbol}")
        return {
            "symbol": symbol,
            "ratios": [],
            "extracted_financials": [],
        }

    # Combine chunk texts for the LLM
    chunks_text = "\n\n---\n\n".join([
        f"[Chunk {c['chunk_id'][:8]}] {c['text']}"
        for c in financial_chunks
    ])
    chunk_ids = [c["chunk_id"] for c in financial_chunks]

    # -----------------------------------------------------------------------
    # Step 2: Extract financial figures via Gemini structured output
    # -----------------------------------------------------------------------
    extraction_prompt = f"""You are a financial data extraction assistant. From the following financial data chunks for {symbol}, 
extract the key financial figures for each available period.

For each period, extract:
- period (e.g., "Mar 2024", "Mar 2023")
- revenue (Sales/Revenue from Operations, in ₹ Crores)
- net_profit (Net Profit/PAT, in ₹ Crores) 
- operating_profit (Operating Profit/EBIT, in ₹ Crores)
- operating_cash_flow (Cash from Operating Activity, in ₹ Crores)
- total_debt (Borrowings/Total Debt, in ₹ Crores)
- total_equity (Share Capital + Reserves, in ₹ Crores)
- inventory (Inventories, in ₹ Crores, null if not available)
- current_assets (Total Current Assets, in ₹ Crores)
- current_liabilities (Total Current Liabilities, in ₹ Crores)

Return ONLY the numbers from the source text. Do NOT calculate or estimate any numbers.

SOURCE DATA:
{chunks_text}"""

    extracted = None
    if llm.is_configured():
        try:
            extracted = llm.generate_structured(
                message=extraction_prompt,
                response_schema=GeminiExtractedFinancials,
                agent_name="analyst_extractor",
                system_instruction="Extract financial figures exactly as they appear in the source data. Do not estimate or calculate values.",
            )
        except Exception as e:
            print(f"[Analyst] LLM extraction failed: {e}")

    # Fallback: parse from chunks directly if LLM fails
    if extracted is None or not extracted.periods:
        extracted = _fallback_extract(financial_chunks, symbol)

    # Attach source chunk IDs to each period
    for period in extracted.periods:
        period.source_chunk_ids = chunk_ids

    # -----------------------------------------------------------------------
    # Step 3: Compute ratios deterministically in Python
    # -----------------------------------------------------------------------
    ratios = _compute_ratios(extracted.periods, chunk_ids)

    # -----------------------------------------------------------------------
    # Step 4: Generate LLM interpretation for the ratios
    # -----------------------------------------------------------------------
    if llm.is_configured() and ratios:
        ratios = await _add_interpretations(llm, ratios, symbol)

    duration_ms = (time.time() - start_time) * 1000
    await log_llm_usage(
        agent_name="analyst",
        model="aggregate",
        latency_ms=duration_ms,
        symbol=symbol,
    )

    result = {
        "symbol": symbol,
        "ratios": [r.model_dump() for r in ratios],
        "extracted_financials": [p.model_dump() for p in extracted.periods],
    }

    print(f"[Analyst] Completed for {symbol}: {len(ratios)} ratios computed "
          f"from {len(extracted.periods)} periods in {duration_ms:.0f}ms")

    return result


def _fallback_extract(chunks: list[dict], symbol: str) -> GeminiExtractedFinancials:
    """
    Parse financial figures directly from chunk text when LLM is unavailable.
    Looks for patterns in the structured text format we created in the retriever.
    """
    periods_data: dict[str, dict] = {}

    for chunk in chunks:
        text = chunk.get("text", "")
        lines = text.split("\n")

        current_period_headers = []

        for line in lines:
            line = line.strip()

            # Look for period headers line
            if line.startswith("Periods:"):
                current_period_headers = [
                    p.strip() for p in line.replace("Periods:", "").split(",")
                ]
                for ph in current_period_headers:
                    if ph and ph not in periods_data:
                        periods_data[ph] = {}
                continue

            # Parse row data (format: "Label: val1 | val2 | val3")
            if ":" in line and "|" in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    label = parts[0].strip()
                    values_str = parts[1].strip().split("|")
                    values = []
                    for v in values_str:
                        v = v.strip().replace("₹", "").replace("Cr", "").replace(",", "").strip()
                        try:
                            values.append(float(v))
                        except (ValueError, TypeError):
                            values.append(None)

                    # Map label to field
                    field_map = {
                        "Sales": "revenue",
                        "Revenue": "revenue",
                        "Net Profit": "net_profit",
                        "Operating Profit": "operating_profit",
                        "Cash from Operating Activity": "operating_cash_flow",
                        "Operating Cash Flow": "operating_cash_flow",
                        "Borrowings": "total_debt",
                        "Total Debt": "total_debt",
                        "Inventories": "inventory",
                        "Total Current Assets": "current_assets",
                        "Total Current Liabilities": "current_liabilities",
                    }

                    field = field_map.get(label)
                    if field and current_period_headers:
                        for i, val in enumerate(values):
                            if i < len(current_period_headers) and val is not None:
                                ph = current_period_headers[i]
                                if ph not in periods_data:
                                    periods_data[ph] = {}
                                periods_data[ph][field] = val

    # Also try "Summary" format: "Period: Mar 2024 | Revenue: ₹X Cr | ..."
    for chunk in chunks:
        text = chunk.get("text", "")
        for line in text.split("\n"):
            if line.startswith("Period:") and "|" in line:
                parts = [p.strip() for p in line.split("|")]
                period_name = ""
                fields = {}
                for part in parts:
                    if part.startswith("Period:"):
                        period_name = part.replace("Period:", "").strip()
                    elif ":" in part:
                        k, v = part.split(":", 1)
                        k = k.strip()
                        v = v.strip().replace("₹", "").replace("Cr", "").replace(",", "").strip()
                        try:
                            val = float(v)
                        except (ValueError, TypeError):
                            val = None

                        field_map = {
                            "Revenue": "revenue",
                            "Net Profit": "net_profit",
                            "Operating Profit": "operating_profit",
                            "Operating Cash Flow": "operating_cash_flow",
                            "Total Debt": "total_debt",
                            "Total Equity": "total_equity",
                            "Inventory": "inventory",
                        }
                        field = field_map.get(k)
                        if field and val is not None:
                            fields[field] = val

                if period_name and fields:
                    if period_name not in periods_data:
                        periods_data[period_name] = {}
                    periods_data[period_name].update(fields)

    # Build ExtractedFinancials objects
    periods = []
    for period_name, data in periods_data.items():
        if data:  # Only include periods with actual data
            periods.append(ExtractedFinancials(
                period=period_name,
                revenue=data.get("revenue"),
                net_profit=data.get("net_profit"),
                operating_profit=data.get("operating_profit"),
                operating_cash_flow=data.get("operating_cash_flow"),
                total_debt=data.get("total_debt"),
                total_equity=data.get("total_equity"),
                inventory=data.get("inventory"),
                current_assets=data.get("current_assets"),
                current_liabilities=data.get("current_liabilities"),
            ))

    return GeminiExtractedFinancials(periods=periods)


def _compute_ratios(periods: list[ExtractedFinancials], chunk_ids: list[str]) -> list[Ratio]:
    """
    Compute financial ratios deterministically in Python.
    No LLM involved in math — only pure Python calculations.
    """
    ratios: list[Ratio] = []

    if len(periods) < 2:
        return ratios

    # Sort by period (most recent first)
    sorted_periods = sorted(periods, key=lambda p: p.period, reverse=True)

    # -----------------------------------------------------------------------
    # Revenue Growth (YoY for consecutive periods)
    # -----------------------------------------------------------------------
    for i in range(len(sorted_periods) - 1):
        curr = sorted_periods[i]
        prev = sorted_periods[i + 1]

        if curr.revenue is not None and prev.revenue is not None and prev.revenue != 0:
            growth = ((curr.revenue - prev.revenue) / prev.revenue) * 100
            ratios.append(Ratio(
                name=f"Revenue Growth ({curr.period} vs {prev.period})",
                value=round(growth, 2),
                unit="%",
                formula=f"({curr.revenue:.0f} - {prev.revenue:.0f}) / {prev.revenue:.0f} × 100",
                periods_compared=[curr.period, prev.period],
                source_chunk_ids=chunk_ids,
            ))

    # -----------------------------------------------------------------------
    # Operating Margin (per period)
    # -----------------------------------------------------------------------
    for p in sorted_periods:
        if p.revenue is not None and p.operating_profit is not None and p.revenue != 0:
            margin = (p.operating_profit / p.revenue) * 100
            ratios.append(Ratio(
                name=f"Operating Margin ({p.period})",
                value=round(margin, 2),
                unit="%",
                formula=f"{p.operating_profit:.0f} / {p.revenue:.0f} × 100",
                periods_compared=[p.period],
                source_chunk_ids=chunk_ids,
            ))

    # -----------------------------------------------------------------------
    # Net Profit Margin (per period)
    # -----------------------------------------------------------------------
    for p in sorted_periods:
        if p.revenue is not None and p.net_profit is not None and p.revenue != 0:
            margin = (p.net_profit / p.revenue) * 100
            ratios.append(Ratio(
                name=f"Net Profit Margin ({p.period})",
                value=round(margin, 2),
                unit="%",
                formula=f"{p.net_profit:.0f} / {p.revenue:.0f} × 100",
                periods_compared=[p.period],
                source_chunk_ids=chunk_ids,
            ))

    # -----------------------------------------------------------------------
    # Debt-to-Equity (per period)
    # -----------------------------------------------------------------------
    for p in sorted_periods:
        if p.total_debt is not None and p.total_equity is not None and p.total_equity != 0:
            de = p.total_debt / p.total_equity
            ratios.append(Ratio(
                name=f"Debt-to-Equity ({p.period})",
                value=round(de, 4),
                unit="x",
                formula=f"{p.total_debt:.0f} / {p.total_equity:.0f}",
                periods_compared=[p.period],
                source_chunk_ids=chunk_ids,
            ))

    # -----------------------------------------------------------------------
    # Current Ratio (per period)
    # -----------------------------------------------------------------------
    for p in sorted_periods:
        if p.current_assets is not None and p.current_liabilities is not None and p.current_liabilities != 0:
            cr = p.current_assets / p.current_liabilities
            ratios.append(Ratio(
                name=f"Current Ratio ({p.period})",
                value=round(cr, 4),
                unit="x",
                formula=f"{p.current_assets:.0f} / {p.current_liabilities:.0f}",
                periods_compared=[p.period],
                source_chunk_ids=chunk_ids,
            ))

    # -----------------------------------------------------------------------
    # Net Profit Growth (YoY)
    # -----------------------------------------------------------------------
    for i in range(len(sorted_periods) - 1):
        curr = sorted_periods[i]
        prev = sorted_periods[i + 1]

        if curr.net_profit is not None and prev.net_profit is not None and prev.net_profit != 0:
            growth = ((curr.net_profit - prev.net_profit) / prev.net_profit) * 100
            ratios.append(Ratio(
                name=f"Net Profit Growth ({curr.period} vs {prev.period})",
                value=round(growth, 2),
                unit="%",
                formula=f"({curr.net_profit:.0f} - {prev.net_profit:.0f}) / {prev.net_profit:.0f} × 100",
                periods_compared=[curr.period, prev.period],
                source_chunk_ids=chunk_ids,
            ))

    return ratios


async def _add_interpretations(llm, ratios: list[Ratio], symbol: str) -> list[Ratio]:
    """Add LLM-generated short interpretations to computed ratios."""
    ratios_summary = "\n".join([
        f"- {r.name}: {r.value}{r.unit} (formula: {r.formula})"
        for r in ratios
    ])

    prompt = f"""You are a financial analyst interpreting key ratios for {symbol}.

For each ratio below, provide a brief 1-sentence interpretation highlighting what it means 
for the company's financial health. Reference the actual numbers.

RATIOS:
{ratios_summary}

Provide an overall interpretation and key highlights."""

    try:
        result = llm.generate_structured(
            message=prompt,
            response_schema=GeminiRatioInterpretation,
            agent_name="analyst_interpreter",
            system_instruction="Provide concise, factual interpretations of financial ratios.",
        )

        # Distribute interpretation across ratios
        if result and result.interpretation:
            # Set overall interpretation on the first ratio and highlights on others
            if ratios:
                ratios[0].interpretation = result.interpretation

            for i, highlight in enumerate(result.key_highlights or []):
                if i < len(ratios):
                    ratios[i].interpretation = highlight

    except Exception as e:
        print(f"[Analyst] Interpretation generation failed: {e}")
        # Non-critical — ratios are still valid without interpretations

    return ratios
