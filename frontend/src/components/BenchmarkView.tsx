import { useEffect, useState } from "react";
import { getBenchmarkResults } from "../api";

type BenchmarkData = {
  total_claims: number;
  overall_accuracy: number;
  precision_supported: number;
  recall_supported: number;
  f1_supported: number;
  precision_unsupported: number;
  recall_unsupported: number;
  f1_unsupported: number;
  precision_contradicted: number;
  recall_contradicted: number;
  f1_contradicted: number;
  confusion_matrix: number[][];
  per_company: Record<string, any>;
  run_at?: string;
};

const LABELS = ["SUPPORTED", "UNSUPPORTED", "CONTRADICTED"];

export default function BenchmarkView() {
  const [data, setData] = useState<BenchmarkData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getBenchmarkResults()
      .then(setData)
      .catch((e) => setError(e.message || "Failed to load"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto px-6 py-16 text-center">
        <svg className="animate-spin h-8 w-8 text-indigo-500 mx-auto mb-4" viewBox="0 0 24 24" fill="none">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        <p className="text-slate-400 text-sm">Loading benchmark results...</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="max-w-4xl mx-auto px-6 py-16 text-center">
        <div className="p-6 rounded-xl bg-slate-900/50 border border-slate-800/40">
          <h3 className="text-lg font-bold text-white mb-2">No Benchmark Results</h3>
          <p className="text-sm text-slate-400 mb-4">
            {error || "No benchmark has been run yet. Run the benchmark script to see results."}
          </p>
          <code className="block text-xs bg-slate-950/60 p-3 rounded-lg text-indigo-400 font-mono">
            py -3 benchmark/run_eval.py
          </code>
        </div>
      </div>
    );
  }

  const metricCard = (label: string, value: number, colorClass: string) => (
    <div className="p-3 rounded-xl bg-slate-900/50 border border-slate-800/40">
      <div className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider">{label}</div>
      <div className={`text-xl font-bold mt-1 ${colorClass}`}>{(value * 100).toFixed(1)}%</div>
    </div>
  );

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      <h2 className="text-xl font-bold text-white mb-1">Benchmark Evaluation</h2>
      <p className="text-xs text-slate-400 mb-8">
        Verifier performance on {data.total_claims} labeled claims
        {data.run_at && <span className="ml-2 text-slate-500">• {new Date(data.run_at).toLocaleString()}</span>}
      </p>

      {/* Overall Accuracy */}
      <div className="mb-8 p-5 rounded-xl bg-gradient-to-br from-indigo-500/10 to-violet-500/10 border border-indigo-500/20">
        <div className="text-xs text-indigo-400 font-semibold uppercase tracking-wider">Overall Accuracy</div>
        <div className="text-3xl font-bold text-white mt-1">{(data.overall_accuracy * 100).toFixed(1)}%</div>
        <div className="text-xs text-slate-400 mt-1">{data.total_claims} claims evaluated</div>
      </div>

      {/* Per-class P/R/F1 */}
      <h3 className="text-sm font-bold text-white mb-3">Per-Class Metrics</h3>
      <div className="grid grid-cols-3 gap-4 mb-8">
        {/* SUPPORTED */}
        <div className="space-y-2">
          <div className="text-xs font-bold text-emerald-400 uppercase tracking-wider">Supported</div>
          {metricCard("Precision", data.precision_supported, "text-emerald-400")}
          {metricCard("Recall", data.recall_supported, "text-emerald-400")}
          {metricCard("F1 Score", data.f1_supported, "text-emerald-400")}
        </div>
        {/* UNSUPPORTED */}
        <div className="space-y-2">
          <div className="text-xs font-bold text-amber-400 uppercase tracking-wider">Unsupported</div>
          {metricCard("Precision", data.precision_unsupported, "text-amber-400")}
          {metricCard("Recall", data.recall_unsupported, "text-amber-400")}
          {metricCard("F1 Score", data.f1_unsupported, "text-amber-400")}
        </div>
        {/* CONTRADICTED */}
        <div className="space-y-2">
          <div className="text-xs font-bold text-rose-400 uppercase tracking-wider">Contradicted</div>
          {metricCard("Precision", data.precision_contradicted, "text-rose-400")}
          {metricCard("Recall", data.recall_contradicted, "text-rose-400")}
          {metricCard("F1 Score", data.f1_contradicted, "text-rose-400")}
        </div>
      </div>

      {/* Confusion Matrix */}
      {data.confusion_matrix && (
        <div className="mb-8">
          <h3 className="text-sm font-bold text-white mb-3">Confusion Matrix</h3>
          <div className="inline-block rounded-xl bg-slate-900/50 border border-slate-800/40 overflow-hidden">
            <table className="text-xs">
              <thead>
                <tr>
                  <th className="p-3 text-slate-500 font-medium">Predicted →</th>
                  {LABELS.map((l) => (
                    <th key={l} className="p-3 text-slate-400 font-semibold">{l.slice(0, 4)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.confusion_matrix.map((row, i) => (
                  <tr key={i}>
                    <td className="p-3 text-slate-400 font-semibold border-t border-slate-800/40">
                      {LABELS[i]?.slice(0, 4)}
                    </td>
                    {row.map((val, j) => (
                      <td
                        key={j}
                        className={`p-3 text-center font-mono font-bold border-t border-slate-800/40 ${
                          i === j
                            ? "text-emerald-400 bg-emerald-500/10"
                            : val > 0
                            ? "text-rose-400 bg-rose-500/5"
                            : "text-slate-600"
                        }`}
                      >
                        {val}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
