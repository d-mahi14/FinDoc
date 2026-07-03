import { useState, useEffect } from "react";

interface HealthResponse {
  status: string;
}

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("http://localhost:8000/api/health")
      .then((res) => {
        if (!res.ok) {
          throw new Error(`HTTP error! status: ${res.status}`);
        }
        return res.json();
      })
      .then((data: HealthResponse) => {
        setHealth(data);
        setError(null);
        setLoading(false);
      })
      .catch((err) => {
        console.error("Health check failed:", err);
        setError(err.message || "Failed to reach backend");
        setHealth(null);
        setLoading(false);
      });
  }, []);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans relative overflow-hidden selection:bg-indigo-500 selection:text-white">
      {/* Premium ambient light filters */}
      <div className="absolute top-[-10%] left-[-10%] w-[50%] h-[50%] bg-indigo-900/20 rounded-full blur-[160px] pointer-events-none" />
      <div className="absolute bottom-[-10%] right-[-10%] w-[50%] h-[50%] bg-violet-900/20 rounded-full blur-[160px] pointer-events-none" />

      {/* Header */}
      <header className="border-b border-slate-900/80 bg-slate-950/40 backdrop-blur-md sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-6 py-5 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-500 to-violet-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
              <span className="text-white font-extrabold text-sm tracking-wider">FD</span>
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-tight bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-transparent">
                FinDocs
              </h1>
              <p className="text-[10px] text-indigo-400 font-semibold uppercase tracking-widest">
                Due-Diligence Multi-Agent System
              </p>
            </div>
          </div>

          <div className="flex items-center gap-4 text-xs">
            <div className="flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-slate-900/80 border border-slate-800">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse" />
              <span className="text-slate-400 font-semibold">Client Online</span>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 max-w-xl mx-auto w-full px-6 flex flex-col justify-center py-16">
        <div className="relative group">
          {/* Neon outer border glow effect */}
          <div className="absolute -inset-[1px] bg-gradient-to-r from-indigo-500 to-violet-600 rounded-2xl opacity-30 group-hover:opacity-45 blur-md transition duration-500" />
          
          <div className="relative bg-slate-900/80 border border-slate-800/60 backdrop-blur-xl rounded-2xl p-8 shadow-2xl">
            <div className="flex flex-col items-center text-center">
              
              {/* Health check circular pulse status */}
              <div className="relative w-20 h-20 flex items-center justify-center mb-6">
                <div className={`absolute inset-0 rounded-full blur-md opacity-40 transition-all duration-500 ${
                  loading ? "bg-amber-500 animate-pulse" : error ? "bg-rose-500 animate-pulse" : "bg-emerald-500 animate-pulse"
                }`} />
                <div className={`w-16 h-16 rounded-full flex items-center justify-center border-2 shadow-inner transition-colors duration-500 ${
                  loading ? "bg-slate-900 border-amber-500" : error ? "bg-slate-900 border-rose-500" : "bg-slate-900 border-emerald-500"
                }`}>
                  {loading ? (
                    <svg className="animate-spin h-6 w-6 text-amber-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                  ) : error ? (
                    <svg className="h-7 w-7 text-rose-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                    </svg>
                  ) : (
                    <svg className="h-8 w-8 text-emerald-500 animate-bounce" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                  )}
                </div>
              </div>

              <h2 className="text-xl font-bold bg-gradient-to-r from-white via-slate-100 to-slate-350 bg-clip-text text-transparent">
                {loading ? "Establishing Connection..." : error ? "Connection Failed" : "System Core Active"}
              </h2>
              <p className="text-xs text-slate-400 mt-2 max-w-sm leading-relaxed">
                {loading 
                  ? "Awaiting backend response from api health check..." 
                  : error 
                  ? "The backend server is offline or unreachable. Please verify that the FastAPI server is running." 
                  : "All system coordinates verified. Project skeleton loaded successfully."}
              </p>

              {/* Status and Payload Detail Block */}
              <div className="w-full mt-6 space-y-3">
                <div className="p-4 rounded-xl bg-slate-950/50 border border-slate-800/80 text-left font-mono">
                  <div className="flex items-center justify-between text-xs text-slate-500 mb-2">
                    <span>ENDPOINT</span>
                    <span className="text-indigo-400 font-semibold">GET /api/health</span>
                  </div>
                  
                  {loading ? (
                    <div className="h-6 bg-slate-900 rounded animate-pulse" />
                  ) : error ? (
                    <div className="text-xs text-rose-400 font-medium">
                      Error: {error}
                    </div>
                  ) : (
                    <pre className="text-xs text-emerald-400 whitespace-pre-wrap font-medium">
                      {JSON.stringify(health, null, 2)}
                    </pre>
                  )}
                </div>

                {/* Details list */}
                <div className="grid grid-cols-2 gap-3 text-left">
                  <div className="p-3.5 rounded-xl bg-slate-950/30 border border-slate-900 text-xs">
                    <p className="text-slate-500 font-semibold uppercase tracking-wider text-[10px]">Framework</p>
                    <p className="text-slate-300 font-medium mt-1">FastAPI + React</p>
                  </div>
                  <div className="p-3.5 rounded-xl bg-slate-950/30 border border-slate-900 text-xs">
                    <p className="text-slate-500 font-semibold uppercase tracking-wider text-[10px]">SDK Client</p>
                    <p className="text-slate-300 font-medium mt-1">Google Gen AI</p>
                  </div>
                </div>
              </div>

            </div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="py-6 border-t border-slate-900/30 bg-slate-950/40 text-center text-[10px] text-slate-500 font-medium tracking-widest uppercase">
        FinDocs &bull; Skeleton Verified
      </footer>
    </div>
  );
}
