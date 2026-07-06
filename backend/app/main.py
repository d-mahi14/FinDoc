import os
# pyrefly: ignore [missing-import]
from contextlib import asynccontextmanager
# pyrefly: ignore [missing-import]
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
# pyrefly: ignore [missing-import]
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

from app.routes import health, retrieve, analyze, verify
from app.utils.llm_client import get_llm_client
from app.utils.db import init_db
from app.utils.vector_store import init_vector_store
from app.utils.ws_manager import ws_manager
# pyrefly: ignore [missing-import]
from google.genai import errors

# Load environment variables from .env if present
load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle for the FastAPI app."""
    # Startup
    print("[App] Initializing database...")
    await init_db()
    print("[App] Initializing vector store...")
    init_vector_store()
    print("[App] Startup complete.")
    yield
    # Shutdown
    print("[App] Shutting down.")


app = FastAPI(title="Financial Due-Diligence System API", lifespan=lifespan)

# Configure CORS so React frontend can talk to FastAPI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router, prefix="/api")
app.include_router(retrieve.router, prefix="/api")
app.include_router(analyze.router, prefix="/api")
app.include_router(verify.router, prefix="/api")


class ChatRequest(BaseModel):
    message: str


@app.get("/")
async def root():
    llm_client = get_llm_client()
    return {
        "status": "online",
        "message": "Hello World from Financial Due-Diligence Backend",
        "gemini_configured": llm_client.is_configured()
    }


@app.post("/api/chat")
async def chat(request: ChatRequest):
    llm_client = get_llm_client()
    if not llm_client.is_configured():
        return {
            "response": (
                "Gemini API key is not configured. Please set the GEMINI_API_KEY environment "
                "variable in a backend/.env file to enable live agent chat.\n\n"
                f"Echoing your input: '{request.message}'"
            ),
            "status": "mock"
        }

    try:
        response_text = llm_client.generate_content(message=request.message)
        return {
            "response": response_text,
            "status": "success"
        }
    except errors.APIError as e:
        raise HTTPException(status_code=500, detail=f"Gemini API Error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")


# ---------------------------------------------------------------------------
# WebSocket endpoint for live pipeline streaming
# ---------------------------------------------------------------------------

@app.websocket("/ws/analyze/{job_id}")
async def websocket_analyze(websocket: WebSocket, job_id: str):
    """WebSocket endpoint for streaming live pipeline status updates."""
    await ws_manager.connect(job_id, websocket)
    try:
        # Keep connection alive, waiting for messages (ping/pong)
        while True:
            data = await websocket.receive_text()
            # Client can send ping to keep alive
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        ws_manager.disconnect(job_id, websocket)
    except Exception:
        ws_manager.disconnect(job_id, websocket)
