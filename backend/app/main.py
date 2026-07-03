import os
# pyrefly: ignore [missing-import]
from fastapi import FastAPI, HTTPException
# pyrefly: ignore [missing-import]
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

from app.routes import health
from app.utils.llm_client import get_llm_client
# pyrefly: ignore [missing-import]
from google.genai import errors

# Load environment variables from .env if present
load_dotenv()

app = FastAPI(title="Financial Due-Diligence System API")

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
        # If API key is not configured, return a mock response that guides the user
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
