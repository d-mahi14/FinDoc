# FinDocs - Multi-Agent Financial Due-Diligence System

A comprehensive skeleton setup for a multi-agent financial due-diligence system, featuring a FastAPI Python backend and a React + Vite + TypeScript + Tailwind CSS frontend.

---

## 🛠️ Project Structure

- **`/backend`**: FastAPI backend app.
  - `app/main.py`: Main application setup.
  - `app/routes/health.py`: Health check route (`GET /api/health`).
  - `app/utils/llm_client.py`: Shared Google Gen AI SDK client.
  - `app/agents/`, `app/models/`, `app/utils/`: Structuring placeholders for agents and data layers.
- **`/frontend`**: React client application.
  - `src/App.tsx`: Main dashboard showcasing connection status, server health payload, and system stats.

---

## 🚀 Setup & Execution Instructions

### 1. Backend Server Setup

Navigate into the backend directory:
```bash
cd backend
```

#### Step A: Configure Environment Variables
Copy the template `.env.example` file to `.env`:
```bash
cp .env.example .env
```
Open the `.env` file and fill in your placeholders:
- `GEMINI_API_KEY`: Your Gemini API Key from Google AI Studio.
- `SCREENER_SESSION_TOKEN`: Session token for scraping Screener financial reports.
- `NEWS_API_KEY`: API Key for accessing finance/market news providers.

#### Step B: Virtual Environment Setup & Installation
Create a Python virtual environment and activate it:
* **Windows (PowerShell)**:
  ```powershell
  python -m venv .venv
  .\.venv\Scripts\Activate.ps1
  ```
* **macOS / Linux**:
  ```bash
  python -m venv .venv
  source .venv/bin/activate
  ```

Install requirements:
```bash
pip install -r requirements.txt
```

#### Step C: Start the FastAPI Server
Run the local uvicorn server in watch mode:
```bash
uvicorn app.main:app --reload --port 8000
```
Verify the server is running by visiting: [http://localhost:8000/api/health](http://localhost:8000/api/health).

---

### 2. Frontend Client Setup

Navigate into the frontend directory:
```bash
cd frontend
```

#### Step A: Install Dependencies
```bash
npm install
```

#### Step B: Run Frontend Development Server
```bash
npm run dev
```
Open your browser and navigate to: [http://localhost:5173/](http://localhost:5173/) to verify the application skeleton and health status displays.
