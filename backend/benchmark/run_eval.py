"""
Benchmark evaluation script for the Verifier Agent.

Runs all labeled claims through the Verifier, computes precision/recall/F1
per class, overall accuracy, and a confusion matrix.

Usage:
    py -3 benchmark/run_eval.py
"""

import asyncio
import json
import os
import sys
import uuid
from collections import Counter
from datetime import datetime

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.utils.db import init_db
from app.utils.vector_store import init_vector_store
from app.agents.retriever import run_retriever
from app.agents.verifier import run_verifier
from app.utils.db import save_benchmark_result


CLAIMS_PATH = os.path.join(os.path.dirname(__file__), "claims.json")
LABELS = ["SUPPORTED", "UNSUPPORTED", "CONTRADICTED"]
LABEL_TO_IDX = {l: i for i, l in enumerate(LABELS)}


async def main():
    print("=" * 60)
    print("FinDocs Benchmark — Verifier Evaluation")
    print("=" * 60)

    # Initialize
    await init_db()
    init_vector_store()

    # Load claims
    with open(CLAIMS_PATH, "r", encoding="utf-8") as f:
        claims = json.load(f)

    print(f"\nLoaded {len(claims)} labeled claims")

    # Group by company
    companies = set(c["company"] for c in claims)
    print(f"Companies: {', '.join(sorted(companies))}")

    # Ensure data is indexed for each company
    for company in companies:
        print(f"\n--- Indexing data for {company}...")
        await run_retriever(company)

    # Run claims through verifier
    print(f"\n--- Running {len(claims)} claims through Verifier...")

    verifier_input = []
    for claim in claims:
        verifier_input.append({
            "claim_text": claim["claim_text"],
            "source_chunk_ids": [],  # Let verifier find sources via semantic search
            "claim_source": "benchmark",
        })

    # Process in batches by company
    all_results = []
    for company in companies:
        company_claims = [
            c for i, c in enumerate(verifier_input)
            if claims[i]["company"] == company
        ]
        company_indices = [
            i for i, c in enumerate(claims)
            if c["company"] == company
        ]

        print(f"  Verifying {len(company_claims)} claims for {company}...")
        results = await run_verifier(company_claims, company)

        for idx, result in zip(company_indices, results):
            all_results.append((idx, result))

    # Sort by original index
    all_results.sort(key=lambda x: x[0])

    # Compute metrics
    print("\n--- Computing metrics...")
    confusion = [[0] * 3 for _ in range(3)]
    correct = 0
    total = len(claims)
    per_company: dict[str, dict] = {}

    for idx, result in all_results:
        ground_truth = claims[idx]["ground_truth_label"]
        predicted = result.get("verdict", "UNSUPPORTED")
        company = claims[idx]["company"]

        gt_idx = LABEL_TO_IDX.get(ground_truth, 1)
        pred_idx = LABEL_TO_IDX.get(predicted, 1)
        confusion[gt_idx][pred_idx] += 1

        if ground_truth == predicted:
            correct += 1

        if company not in per_company:
            per_company[company] = {"correct": 0, "total": 0}
        per_company[company]["total"] += 1
        if ground_truth == predicted:
            per_company[company]["correct"] += 1

    accuracy = correct / total if total > 0 else 0

    # Per-class P/R/F1
    metrics = {}
    for label in LABELS:
        idx = LABEL_TO_IDX[label]
        tp = confusion[idx][idx]
        fp = sum(confusion[j][idx] for j in range(3)) - tp
        fn = sum(confusion[idx][j] for j in range(3)) - tp

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

        metrics[label] = {"precision": precision, "recall": recall, "f1": f1}

    # Print results
    print(f"\n{'=' * 60}")
    print(f"RESULTS")
    print(f"{'=' * 60}")
    print(f"Overall Accuracy: {accuracy:.1%} ({correct}/{total})")
    print()

    for label in LABELS:
        m = metrics[label]
        print(f"  {label:15s}  P={m['precision']:.3f}  R={m['recall']:.3f}  F1={m['f1']:.3f}")

    print(f"\nConfusion Matrix (rows=actual, cols=predicted):")
    print(f"{'':>15s} {'SUPP':>6s} {'UNSU':>6s} {'CONT':>6s}")
    for i, label in enumerate(LABELS):
        row = " ".join(f"{v:>6d}" for v in confusion[i])
        print(f"{label[:15]:>15s} {row}")

    print(f"\nPer Company:")
    for company, stats in sorted(per_company.items()):
        acc = stats["correct"] / stats["total"] if stats["total"] > 0 else 0
        print(f"  {company}: {acc:.1%} ({stats['correct']}/{stats['total']})")

    # Save results to DB
    run_id = str(uuid.uuid4())
    result_data = {
        "run_id": run_id,
        "run_at": datetime.utcnow().isoformat(),
        "total_claims": total,
        "overall_accuracy": accuracy,
        "precision_supported": metrics["SUPPORTED"]["precision"],
        "recall_supported": metrics["SUPPORTED"]["recall"],
        "f1_supported": metrics["SUPPORTED"]["f1"],
        "precision_unsupported": metrics["UNSUPPORTED"]["precision"],
        "recall_unsupported": metrics["UNSUPPORTED"]["recall"],
        "f1_unsupported": metrics["UNSUPPORTED"]["f1"],
        "precision_contradicted": metrics["CONTRADICTED"]["precision"],
        "recall_contradicted": metrics["CONTRADICTED"]["recall"],
        "f1_contradicted": metrics["CONTRADICTED"]["f1"],
        "confusion_matrix": confusion,
        "per_company": {k: {"accuracy": v["correct"]/v["total"] if v["total"] else 0, **v} for k, v in per_company.items()},
    }

    await save_benchmark_result(run_id, result_data)
    print(f"\nResults saved to DB (run_id: {run_id[:8]}...)")
    print("View at: GET http://localhost:8000/api/benchmark/results")


if __name__ == "__main__":
    asyncio.run(main())
