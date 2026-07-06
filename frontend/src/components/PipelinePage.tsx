import { useEffect, useState, useRef } from "react";
import { useParams, useLocation, useNavigate } from "react-router-dom";
import { connectPipelineWs } from "../api";

type AgentStatus = {
  agent_name: string;
  status: "pending" | "in_progress" | "complete" | "error";
  message: string;
  duration_ms?: number;
};

const AGENT_ORDER = [
  { key: "retriever", label: "Retriever", icon: "📥", desc: "Fetch & index data" },
  { key: "analyst", label: "Analyst", icon: "📊", desc: "Extract financials & ratios" },
  { key: "red_flag", label: "Red-Flag", icon: "🚩", desc: "Detect risk signals" },
  { key: "narrative", label: "Narrative", icon: "📝", desc: "Analyze news & filings" },
  { key: "verifier", label: "Verifier", icon: "✅", desc: "Verify all claims" },
  { key: "report_generator", label: "Report", icon: "📋", desc: "Compile final report" },
];

export default function PipelinePage() {
  const { jobId } = useParams<{ jobId: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const symbol = (location.state as any)?.symbol || "";

  const [agents, setAgents] = useState<Record<string, AgentStatus>>(() => {
    const init: Record<string, AgentStatus> = {};
    AGENT_ORDER.forEach((a) => {
      init[a.key] = { agent_name: a.key, status: "pending", message: "" };
    });
    return init;
  });

  const [pipelineComplete, setPipelineComplete] = useState(false);
  const [wsError, setWsError] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!jobId) return;

    const ws = connectPipelineWs(
      jobId,
      (data) => {
        if (data.type === "agent_status") {
          setAgents((prev) => ({
            ...prev,
            [data.agent_name]: {
              agent_name: data.agent_name,
              status: data.status,
              message: data.message || "",
              duration_ms: data.duration_ms,
            },
          }));
        } else if (data.type === "pipeline_complete") {
          setPipelineComplete(true);
        } else if (data.type === "error") {
          if (data.agent_name) {
            setAgents((prev) => ({
              ...prev,
              [data.agent_name]: {
                ...prev[data.agent_name],
                status: "error",
                message: data.message || "Error",
              },
            }));
          }
        }
      },
      () => { /* ws closed */ },
      () => setWsError(true),
    );
    wsRef.current = ws;

    return () => {
      ws.close();
    };
  }, [jobId]);

  // Auto-navigate to report when complete
  useEffect(() => {
    if (pipelineComplete && jobId) {
      const timer = setTimeout(() => navigate(`/report/${jobId}`), 1200);
      return () => clearTimeout(timer);
    }
  }, [pipelineComplete, jobId, navigate]);

  const statusColor = (s: string) => {
    switch (s) {
      case "complete": return "text-emerald-400 border-emerald-500/40 bg-emerald-500/10";
      case "in_progress": return "text-amber-400 border-amber-500/40 bg-amber-500/10";
      case "error": return "text-rose-400 border-rose-500/40 bg-rose-500/10";
      default: return "text-slate-500 border-slate-700/40 bg-slate-800/30";
    }
  };

  const statusIcon = (s: string) => {
    switch (s) {
      case "complete": return "✓";
      case "in_progress": return "⟳";
      case "error": return "✗";
      default: return "○";
    }
  };

  return (
    <div className="max-w-2xl mx-auto px-6 py-12">
      {/* Header */}
      <div className="text-center mb-10">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 text-[10px] font-bold uppercase tracking-widest mb-3">
          <span className={`w-1.5 h-1.5 rounded-full ${pipelineComplete ? "bg-emerald-400" : "bg-amber-400 animate-pulse"}`} />
          {pipelineComplete ? "Pipeline Complete" : "Pipeline Running"}
        </div>
        <h2 className="text-2xl font-bold text-white">
          Analyzing <span className="text-indigo-400">{symbol || jobId?.slice(0, 8)}</span>
        </h2>
      </div>

      {wsError && (
        <div className="mb-6 px-4 py-3 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400 text-xs text-center">
          WebSocket connection failed. Status updates may be delayed.
        </div>
      )}

      {/* Agent Pipeline Steps */}
      <div className="space-y-3">
        {AGENT_ORDER.map((agent, i) => {
          const status = agents[agent.key];
          const isActive = status?.status === "in_progress";

          return (
            <div key={agent.key} className="relative">
              {/* Connector line */}
              {i < AGENT_ORDER.length - 1 && (
                <div className="absolute left-6 top-full w-0.5 h-3 bg-slate-800/60 z-0" />
              )}

              <div
                className={`relative flex items-center gap-4 p-4 rounded-xl border transition-all duration-300 ${statusColor(status?.status || "pending")} ${isActive ? "scale-[1.01] shadow-lg" : ""}`}
              >
                {/* Status indicator */}
                <div className={`w-8 h-8 rounded-lg flex items-center justify-center text-sm font-bold shrink-0 ${isActive ? "animate-spin-slow" : ""}`}>
                  {status?.status === "in_progress" ? (
                    <svg className="animate-spin h-5 w-5 text-amber-400" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                  ) : (
                    <span className="text-lg">{statusIcon(status?.status || "pending")}</span>
                  )}
                </div>

                {/* Agent info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-base">{agent.icon}</span>
                    <span className="text-sm font-bold">{agent.label}</span>
                    <span className="text-[10px] text-slate-500">{agent.desc}</span>
                  </div>
                  {status?.message && (
                    <p className="text-xs mt-1 opacity-80 truncate">{status.message}</p>
                  )}
                </div>

                {/* Duration */}
                {status?.duration_ms != null && (
                  <span className="text-[10px] font-mono text-slate-500 shrink-0">
                    {(status.duration_ms / 1000).toFixed(1)}s
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Pipeline complete CTA */}
      {pipelineComplete && (
        <div className="mt-8 text-center animate-fade-in">
          <button
            onClick={() => navigate(`/report/${jobId}`)}
            className="px-8 py-3 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-600 text-white font-bold text-sm shadow-lg shadow-emerald-500/25 hover:shadow-emerald-500/40 hover:scale-[1.02] active:scale-[0.98] transition-all"
          >
            View Report →
          </button>
        </div>
      )}
    </div>
  );
}
