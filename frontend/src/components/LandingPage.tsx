import { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { startAnalysis } from "../api";

const SUGGESTED = ["TCS", "RELIANCE", "INFY", "HDFCBANK", "WIPRO"];

export default function LandingPage() {
  const [symbol, setSymbol] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const handleAnalyze = useCallback(async () => {
    const sym = symbol.trim().toUpperCase();
    if (!sym) return;
    setLoading(true);
    setError(null);
    try {
      const data = await startAnalysis(sym);
      navigate(`/pipeline/${data.job_id}`, { state: { symbol: sym } });
    } catch (e: any) {
      setError(e.message || "Failed to start analysis");
    } finally {
      setLoading(false);
    }
  }, [symbol, navigate]);

  return (
    <div className="max-w-2xl mx-auto px-6 flex flex-col items-center justify-center min-h-[calc(100vh-140px)]">
      {/* Hero */}
      <div className="text-center mb-10">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 text-[10px] font-bold uppercase tracking-widest mb-6">
          <span className="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-pulse" />
          AI-Powered Financial Analysis
        </div>
        <h2 className="text-3xl sm:text-4xl font-bold bg-gradient-to-br from-white via-slate-200 to-slate-500 bg-clip-text text-transparent leading-tight">
          Deep Due-Diligence
          <br />
          <span className="text-2xl sm:text-3xl">for Indian Listed Companies</span>
        </h2>
        <p className="mt-4 text-sm text-slate-400 max-w-md mx-auto leading-relaxed">
          Enter an NSE/BSE symbol to trigger a multi-agent pipeline that retrieves financials,
          computes ratios, flags risks, verifies every claim, and generates a cited report.
        </p>
      </div>

      {/* Search Card */}
      <div className="w-full relative group">
        <div className="absolute -inset-[1px] bg-gradient-to-r from-indigo-500 to-violet-600 rounded-2xl opacity-20 group-hover:opacity-35 blur-md transition duration-500" />
        <div className="relative bg-slate-900/80 border border-slate-800/60 backdrop-blur-xl rounded-2xl p-6 shadow-2xl">
          <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
            Company Symbol
          </label>
          <div className="flex gap-3">
            <input
              type="text"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              onKeyDown={(e) => e.key === "Enter" && handleAnalyze()}
              placeholder="e.g. TCS, RELIANCE, INFY"
              className="flex-1 bg-slate-950/60 border border-slate-700/60 rounded-xl px-4 py-3 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500/50 focus:ring-1 focus:ring-indigo-500/30 transition-all"
              disabled={loading}
              autoFocus
            />
            <button
              onClick={handleAnalyze}
              disabled={loading || !symbol.trim()}
              className="px-6 py-3 rounded-xl bg-gradient-to-r from-indigo-500 to-violet-600 text-white text-sm font-bold shadow-lg shadow-indigo-500/25 hover:shadow-indigo-500/40 hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100 transition-all"
            >
              {loading ? (
                <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              ) : (
                "Analyze"
              )}
            </button>
          </div>

          {error && (
            <div className="mt-3 px-4 py-2 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-400 text-xs">
              {error}
            </div>
          )}

          {/* Quick select */}
          <div className="mt-4 flex flex-wrap gap-2">
            <span className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider pt-1">Quick:</span>
            {SUGGESTED.map((s) => (
              <button
                key={s}
                onClick={() => { setSymbol(s); }}
                className="px-3 py-1 rounded-lg bg-slate-800/60 border border-slate-700/40 text-slate-300 text-xs font-medium hover:bg-slate-700/60 hover:border-indigo-500/30 hover:text-indigo-300 transition-all"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Feature grid */}
      <div className="grid grid-cols-3 gap-3 mt-8 w-full max-w-lg">
        {[
          { icon: "📊", label: "Ratio Analysis", sub: "Deterministic Python math" },
          { icon: "🚩", label: "Red Flag Detection", sub: "Rule + LLM hybrid" },
          { icon: "✅", label: "Claim Verification", sub: "Source-cited entailment" },
        ].map((f) => (
          <div
            key={f.label}
            className="p-3 rounded-xl bg-slate-900/40 border border-slate-800/40 text-center hover:border-indigo-500/20 transition-colors"
          >
            <div className="text-xl mb-1">{f.icon}</div>
            <div className="text-[11px] font-semibold text-slate-200">{f.label}</div>
            <div className="text-[9px] text-slate-500 mt-0.5">{f.sub}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
