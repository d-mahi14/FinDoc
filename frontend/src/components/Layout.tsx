import { Outlet, Link, useLocation } from "react-router-dom";

const NAV_ITEMS = [
  { path: "/", label: "Analyze" },
  { path: "/benchmark", label: "Benchmark" },
];

export default function Layout() {
  const location = useLocation();

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans relative overflow-hidden selection:bg-indigo-500 selection:text-white">
      {/* Ambient glow */}
      <div className="absolute top-[-10%] left-[-10%] w-[50%] h-[50%] bg-indigo-900/15 rounded-full blur-[160px] pointer-events-none" />
      <div className="absolute bottom-[-10%] right-[-10%] w-[50%] h-[50%] bg-violet-900/15 rounded-full blur-[160px] pointer-events-none" />

      {/* Header */}
      <header className="border-b border-slate-800/60 bg-slate-950/60 backdrop-blur-xl sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-3 group">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-500 to-violet-600 flex items-center justify-center shadow-lg shadow-indigo-500/20 group-hover:shadow-indigo-500/40 transition-shadow">
              <span className="text-white font-extrabold text-xs tracking-wider">FD</span>
            </div>
            <div>
              <h1 className="text-base font-bold tracking-tight bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-transparent">
                FinDocs
              </h1>
              <p className="text-[9px] text-indigo-400 font-semibold uppercase tracking-[0.2em]">
                Due-Diligence Engine
              </p>
            </div>
          </Link>

          <nav className="flex items-center gap-1">
            {NAV_ITEMS.map((item) => {
              const isActive =
                item.path === "/"
                  ? location.pathname === "/"
                  : location.pathname.startsWith(item.path);
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  className={`px-4 py-2 rounded-lg text-xs font-semibold transition-all ${
                    isActive
                      ? "bg-indigo-500/15 text-indigo-300 border border-indigo-500/30"
                      : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 relative z-10">
        <Outlet />
      </main>

      {/* Footer */}
      <footer className="py-4 border-t border-slate-900/50 text-center text-[10px] text-slate-600 font-medium tracking-widest uppercase">
        FinDocs &bull; Multi-Agent Financial Due-Diligence
      </footer>
    </div>
  );
}
