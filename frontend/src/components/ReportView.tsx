import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { getReport, reverifyClaimApi } from "../api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Verification = {
  claim_id?: string;
  verdict: string;
  confidence: number;
  source_excerpt: string;
  explanation: string;
};

type Claim = {
  claim_text: string;
  claim_source: string;
  verification: Verification;
};

type Ratio = {
  name: string;
  value: number | null;
  unit: string;
  formula: string;
  interpretation?: string;
  periods_compared?: string[];
};

type RedFlag = {
  flag_name: string;
  severity: string;
  trigger_rule: string;
  underlying_numbers: Record<string, any>;
  explanation: string;
};

type Report = {
  job_id: string;
  symbol: string;
  company_name: string;
  generated_at: string;
  overview: string;
  ratios: Ratio[];
  red_flags: RedFlag[];
  narrative: {
    claims: { claim_text: string; source_type: string }[];
    overall_tone: string;
    summary_text: string;
  };
  all_claims: Claim[];
  overall_confidence: number;
  data_sources_used: string[];
  financial_periods: any[];
};

export default function ReportView() {
  const { jobId } = useParams<{ jobId: string }>();
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedClaim, setExpandedClaim] = useState<number | null>(null);
  const [reverifying, setReverifying] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;

    const fetchReport = async () => {
      try {
        const data = await getReport(jobId);
        if (!cancelled) {
          if (data.status === "in_progress") {
            setTimeout(fetchReport, 2000);
          } else {
            setReport(data);
            setLoading(false);
          }
        }
      } catch (e: any) {
        if (!cancelled) {
          setError(e.message);
          setLoading(false);
        }
      }
    };

    fetchReport();
    return () => { cancelled = true; };
  }, [jobId]);

  const handleReverify = async (claimIndex: number) => {
    if (!jobId || !report) return;
    const claim = report.all_claims[claimIndex];
    const claimId = claim.verification?.claim_id || claim.claim_text.slice(0, 50);

    setReverifying(claimId);
    try {
      const newVerification = await reverifyClaimApi(jobId, claimId);
      setReport((prev) => {
        if (!prev) return prev;
        const updated = { ...prev };
        updated.all_claims = [...updated.all_claims];
        updated.all_claims[claimIndex] = {
          ...updated.all_claims[claimIndex],
          verification: newVerification,
        };
        return updated;
      });
    } catch (e) {
      console.error("Re-verify failed:", e);
    } finally {
      setReverifying(null);
    }
  };

  if (loading) {
    return (
      <div className="max-w-5xl mx-auto px-6 py-16 text-center">
        <svg className="animate-spin h-8 w-8 text-indigo-500 mx-auto mb-4" viewBox="0 0 24 24" fill="none">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        <p className="text-slate-400 text-sm">Loading report...</p>
      </div>
    );
  }

  if (error || !report) {
    return (
      <div className="max-w-5xl mx-auto px-6 py-16 text-center">
        <div className="px-6 py-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400 text-sm inline-block">
          {error || "Report not found"}
        </div>
        <div className="mt-4">
          <Link to="/" className="text-indigo-400 text-sm hover:underline">← Back to Analysis</Link>
        </div>
      </div>
    );
  }

  const verdictBadge = (v: string) => {
    switch (v) {
      case "SUPPORTED": return "bg-emerald-500/15 text-emerald-400 border-emerald-500/30";
      case "CONTRADICTED": return "bg-rose-500/15 text-rose-400 border-rose-500/30";
      default: return "bg-amber-500/15 text-amber-400 border-amber-500/30";
    }
  };

  const severityColor = (s: string) => {
    switch (s) {
      case "high": return "bg-rose-500/15 text-rose-400 border-rose-500/30";
      case "medium": return "bg-amber-500/15 text-amber-400 border-amber-500/30";
      default: return "bg-slate-700/30 text-slate-400 border-slate-600/30";
    }
  };

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      {/* Report Header */}
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-3">
          <Link to="/" className="text-slate-500 hover:text-indigo-400 text-xs transition-colors">← New Analysis</Link>
        </div>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 className="text-2xl font-bold text-white">{report.company_name}</h2>
            <p className="text-sm text-slate-400 mt-1">
              Symbol: <span className="text-indigo-400 font-mono">{report.symbol}</span>
              {report.data_sources_used?.length > 0 && (
                <span className="ml-3">Sources: {report.data_sources_used.join(", ")}</span>
              )}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <div className="px-4 py-2 rounded-xl bg-slate-900/60 border border-slate-800/60">
              <div className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">Confidence</div>
              <div className={`text-lg font-bold ${report.overall_confidence >= 60 ? "text-emerald-400" : report.overall_confidence >= 40 ? "text-amber-400" : "text-rose-400"}`}>
                {report.overall_confidence.toFixed(0)}%
              </div>
            </div>
            <div className="px-4 py-2 rounded-xl bg-slate-900/60 border border-slate-800/60">
              <div className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">Claims</div>
              <div className="text-lg font-bold text-white">{report.all_claims.length}</div>
            </div>
            <div className="px-4 py-2 rounded-xl bg-slate-900/60 border border-slate-800/60">
              <div className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">Red Flags</div>
              <div className={`text-lg font-bold ${report.red_flags.length > 0 ? "text-rose-400" : "text-emerald-400"}`}>
                {report.red_flags.length}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Overview */}
      {report.overview && (
        <div className="mb-6 p-5 rounded-xl bg-slate-900/50 border border-slate-800/50">
          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Overview</h3>
          <p className="text-sm text-slate-200 leading-relaxed">{report.overview}</p>
        </div>
      )}

      {/* Key Metrics Grid */}
      {report.ratios.length > 0 && (
        <div className="mb-8">
          <h3 className="text-sm font-bold text-white mb-4 flex items-center gap-2">
            <span className="text-base">📊</span> Financial Ratios
          </h3>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {report.ratios.slice(0, 16).map((ratio, i) => (
              <div
                key={i}
                className="p-3 rounded-xl bg-slate-900/50 border border-slate-800/40 hover:border-indigo-500/30 transition-colors group cursor-default"
                title={ratio.formula}
              >
                <div className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider truncate">
                  {ratio.name}
                </div>
                <div className="text-lg font-bold text-white mt-1">
                  {ratio.value != null ? `${ratio.value}${ratio.unit}` : "N/A"}
                </div>
                {ratio.interpretation && (
                  <div className="text-[10px] text-slate-400 mt-1 opacity-0 group-hover:opacity-100 transition-opacity line-clamp-2">
                    {ratio.interpretation}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Red Flags */}
      {report.red_flags.length > 0 && (
        <div className="mb-8">
          <h3 className="text-sm font-bold text-white mb-4 flex items-center gap-2">
            <span className="text-base">🚩</span> Red Flags ({report.red_flags.length})
          </h3>
          <div className="space-y-3">
            {report.red_flags.map((flag, i) => (
              <div
                key={i}
                className={`p-4 rounded-xl border ${severityColor(flag.severity)}`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase border ${severityColor(flag.severity)}`}>
                    {flag.severity}
                  </span>
                  <span className="text-sm font-bold">{flag.flag_name}</span>
                </div>
                <p className="text-xs leading-relaxed mt-2 opacity-90">{flag.explanation}</p>
                <p className="text-[10px] mt-2 opacity-60">{flag.trigger_rule}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Narrative */}
      {report.narrative?.summary_text && (
        <div className="mb-8">
          <h3 className="text-sm font-bold text-white mb-4 flex items-center gap-2">
            <span className="text-base">📝</span> Narrative Summary
            <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase border ${
              report.narrative.overall_tone === "positive" ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" :
              report.narrative.overall_tone === "negative" ? "bg-rose-500/15 text-rose-400 border-rose-500/30" :
              "bg-slate-700/30 text-slate-400 border-slate-600/30"
            }`}>
              {report.narrative.overall_tone}
            </span>
          </h3>
          <div className="p-4 rounded-xl bg-slate-900/50 border border-slate-800/40">
            <p className="text-sm text-slate-200 leading-relaxed">{report.narrative.summary_text}</p>
          </div>
        </div>
      )}

      {/* Claims & Verification Table */}
      <div className="mb-8">
        <h3 className="text-sm font-bold text-white mb-4 flex items-center gap-2">
          <span className="text-base">✅</span> Claims & Verification ({report.all_claims.length})
        </h3>
        <div className="space-y-2">
          {report.all_claims.map((claim, i) => {
            const v = claim.verification;
            const isExpanded = expandedClaim === i;

            return (
              <div key={i} className="rounded-xl bg-slate-900/50 border border-slate-800/40 overflow-hidden">
                <div
                  className="flex items-start gap-3 p-3 cursor-pointer hover:bg-slate-800/30 transition-colors"
                  onClick={() => setExpandedClaim(isExpanded ? null : i)}
                >
                  {/* Verdict badge */}
                  <span className={`shrink-0 px-2 py-0.5 rounded text-[10px] font-bold uppercase border ${verdictBadge(v?.verdict)}`}>
                    {v?.verdict || "N/A"}
                  </span>

                  {/* Claim text */}
                  <span className="flex-1 text-xs text-slate-200 leading-relaxed">{claim.claim_text}</span>

                  {/* Confidence */}
                  <span className="shrink-0 text-[10px] font-mono text-slate-500">
                    {v?.confidence ?? 0}%
                  </span>

                  {/* Source badge */}
                  <span className="shrink-0 px-2 py-0.5 rounded bg-slate-800/60 text-[10px] text-slate-500 font-medium">
                    {claim.claim_source}
                  </span>

                  {/* Expand arrow */}
                  <span className={`shrink-0 text-slate-600 transition-transform ${isExpanded ? "rotate-180" : ""}`}>
                    ▾
                  </span>
                </div>

                {/* Expanded details */}
                {isExpanded && v && (
                  <div className="px-4 pb-3 pt-1 border-t border-slate-800/40 space-y-2">
                    {v.explanation && (
                      <div>
                        <div className="text-[10px] text-slate-500 font-semibold uppercase mb-1">Explanation</div>
                        <p className="text-xs text-slate-300">{v.explanation}</p>
                      </div>
                    )}
                    {v.source_excerpt && (
                      <div>
                        <div className="text-[10px] text-slate-500 font-semibold uppercase mb-1">Source Excerpt</div>
                        <div className="text-xs text-slate-400 bg-slate-950/50 rounded-lg p-3 font-mono max-h-40 overflow-y-auto">
                          {v.source_excerpt}
                        </div>
                      </div>
                    )}
                    <button
                      onClick={(e) => { e.stopPropagation(); handleReverify(i); }}
                      disabled={reverifying === (v.claim_id || claim.claim_text.slice(0, 50))}
                      className="mt-2 px-3 py-1.5 rounded-lg bg-indigo-500/15 border border-indigo-500/30 text-indigo-400 text-[10px] font-bold uppercase tracking-wider hover:bg-indigo-500/25 disabled:opacity-50 transition-all"
                    >
                      {reverifying === (v.claim_id || claim.claim_text.slice(0, 50)) ? "Re-verifying..." : "Re-verify"}
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
