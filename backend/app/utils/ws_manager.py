"""
WebSocket connection manager for streaming pipeline status updates.
Connections are keyed by job_id so each analysis pipeline streams to its own client(s).
"""

import json
from datetime import datetime
from typing import Any

# pyrefly: ignore [missing-import]
from fastapi import WebSocket


class ConnectionManager:
    """
    Manages WebSocket connections for live pipeline status updates.
    Each job_id can have multiple connected clients.
    """

    def __init__(self):
        # job_id -> list of active WebSocket connections
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, job_id: str, websocket: WebSocket):
        """Accept and register a WebSocket connection for a job."""
        await websocket.accept()
        if job_id not in self.active_connections:
            self.active_connections[job_id] = []
        self.active_connections[job_id].append(websocket)
        print(f"[WS] Client connected for job {job_id}")

    def disconnect(self, job_id: str, websocket: WebSocket):
        """Remove a WebSocket connection."""
        if job_id in self.active_connections:
            self.active_connections[job_id] = [
                ws for ws in self.active_connections[job_id] if ws != websocket
            ]
            if not self.active_connections[job_id]:
                del self.active_connections[job_id]
        print(f"[WS] Client disconnected for job {job_id}")

    async def send_update(self, job_id: str, data: dict):
        """
        Send a JSON status update to all clients connected for a job.
        Silently removes any disconnected clients.
        """
        if job_id not in self.active_connections:
            return

        disconnected = []
        for websocket in self.active_connections[job_id]:
            try:
                await websocket.send_json(data)
            except Exception:
                disconnected.append(websocket)

        # Clean up disconnected clients
        for ws in disconnected:
            self.disconnect(job_id, ws)

    async def send_agent_status(
        self,
        job_id: str,
        agent_name: str,
        status: str,
        message: str = "",
        duration_ms: float | None = None
    ):
        """Convenience method to send a typed agent status update."""
        await self.send_update(job_id, {
            "type": "agent_status",
            "agent_name": agent_name,
            "status": status,
            "message": message,
            "timestamp": datetime.utcnow().isoformat(),
            "duration_ms": duration_ms,
        })

    async def send_pipeline_complete(self, job_id: str, report_available: bool = True):
        """Notify clients that the full pipeline has completed."""
        await self.send_update(job_id, {
            "type": "pipeline_complete",
            "job_id": job_id,
            "report_available": report_available,
            "timestamp": datetime.utcnow().isoformat(),
        })

    async def send_error(self, job_id: str, error_message: str, agent_name: str = ""):
        """Notify clients of an error."""
        await self.send_update(job_id, {
            "type": "error",
            "agent_name": agent_name,
            "message": error_message,
            "timestamp": datetime.utcnow().isoformat(),
        })

    def get_connection_count(self, job_id: str) -> int:
        """Get the number of active connections for a job."""
        return len(self.active_connections.get(job_id, []))


# Shared singleton instance
ws_manager = ConnectionManager()
