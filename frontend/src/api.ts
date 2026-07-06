const API_BASE = "http://localhost:8000/api";
const WS_BASE = "ws://localhost:8000";

// ---------------------------------------------------------------------------
// REST API
// ---------------------------------------------------------------------------

export async function healthCheck() {
  const res = await fetch(`${API_BASE}/health`);
  return res.json();
}

export async function startAnalysis(symbol: string) {
  const res = await fetch(`${API_BASE}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol }),
  });
  if (!res.ok) throw new Error(`Analysis start failed: ${res.status}`);
  return res.json();
}

export async function getReport(jobId: string) {
  const res = await fetch(`${API_BASE}/report/${jobId}`);
  if (!res.ok && res.status !== 404) throw new Error(`Report fetch failed: ${res.status}`);
  return res.json();
}

export async function getJobStatus(jobId: string) {
  const res = await fetch(`${API_BASE}/job/${jobId}/status`);
  return res.json();
}

export async function reverifyClaimApi(jobId: string, claimId: string) {
  const res = await fetch(`${API_BASE}/reverify/${jobId}/${claimId}`, { method: "POST" });
  if (!res.ok) throw new Error(`Re-verify failed: ${res.status}`);
  return res.json();
}

export async function getBenchmarkResults() {
  const res = await fetch(`${API_BASE}/benchmark/results`);
  if (!res.ok) throw new Error(`Benchmark fetch failed: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// WebSocket
// ---------------------------------------------------------------------------

export function connectPipelineWs(
  jobId: string,
  onMessage: (data: any) => void,
  onClose?: () => void,
  onError?: (err: Event) => void,
): WebSocket {
  const ws = new WebSocket(`${WS_BASE}/ws/analyze/${jobId}`);

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      onMessage(data);
    } catch {
      console.error("WS parse error", event.data);
    }
  };

  ws.onclose = () => onClose?.();
  ws.onerror = (e) => onError?.(e);

  // Keep-alive ping every 25s
  const pingInterval = setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send("ping");
    } else {
      clearInterval(pingInterval);
    }
  }, 25000);

  return ws;
}
