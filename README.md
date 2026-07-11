# UML Chatbot

A chat platform that accepts a natural language software design description and generates UML diagrams in real-time. 

---

## What it does

- Describe a system in plain English → get rendered UML diagrams back
- Supports all 14 UML 2.x diagram types (sequence, class, component, activity, use case, state machine, deployment, and more)
- Diagrams stream to the browser as they're generated — you see each one finish independently
- Iterative: send an updated prompt to refine the diagrams, history is preserved
- Feedback: rate diagrams and leave comments (wired to a LangChain ART training stub for RL fine-tuning)

### Input format

```json
{
  "prompt": "I am working on a compliance monitoring solution which will pull in the latest circulars from SEBI...",
  "diagram_types": ["sequence", "component", "class"]
}
```

`diagram_types` is optional — the LLM will auto-select the most relevant types if omitted.

---

## Tech stack

| Layer | Stack |
|---|---|
| Frontend | React 19, Vite, plain CSS (no UI framework) |
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2.0 async, aiosqlite |
| LLM | Groq API — `llama-3.3-70b-versatile` (~700 tok/s) |
| LLM orchestration | LangChain 0.3 |
| Diagram rendering | PlantUML server (Docker) |
| Auth | JWT (PyJWT, HS256) |
| Realtime | WebSocket (FastAPI native) |
| DB | SQLite (file-based, auto-created on startup) |

---

## Architecture in brief

```
Browser (React)
    │  REST /api/v1          │  WebSocket /ws/stream/{message_id}
FastAPI Backend
    └── BackgroundTasks → Orchestrator
            └── asyncio.gather (all diagram types in parallel)
                    ├── Planner (Groq LLM) → IR JSON
                    ├── Validator (Pydantic) + Repair Agent (up to 3 retries)
                    ├── Code Generator (IR → PlantUML DSL, deterministic)
                    └── Renderer (HTTP → PlantUML Docker server → SVG)
```

**Key design decision — IR layer:** The LLM outputs a validated JSON Intermediate Representation (IR), not raw PlantUML DSL. A deterministic code generator then converts IR to DSL. This makes validation, error repair, and ART training significantly cleaner. See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the full breakdown.

---

## Prerequisites

- Python 3.11+
- Node.js 18+
- Docker (for the PlantUML rendering server)
- A [Groq API key](https://console.groq.com) (free tier is sufficient)

---

## Local setup

### 1. Start the PlantUML server

```bash
docker-compose up -d
```

Starts `plantuml/plantuml-server:jetty` on port 8090. The backend needs this running before it can render diagrams.

### 2. Configure the backend

```bash
cd backend
cp .env.example .env
```

Edit `.env` and fill in:

```
GROQ_API_KEY=your_groq_api_key_here
JWT_SECRET=any-long-random-string
DATABASE_URL=sqlite+aiosqlite:///./uml_chatbot.db
PLANTUML_SERVER_URL=http://localhost:8090
LLM_MODEL=llama-3.3-70b-versatile
```

### 3. Install backend dependencies and start

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The database is created automatically on first startup. Swagger UI available at `http://localhost:8000/docs`.

### 4. Install frontend dependencies and start

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

---

## Usage

1. Register an account (or log in if you've done this before)
2. Create a new session
3. Type a software design description and select diagram types (or leave blank for auto-selection)
4. Diagrams stream in as they're generated — each one appears as soon as it's ready
5. Click any diagram card to see the raw PlantUML code, zoom in/out, or export
6. To refine: type an updated prompt in the same session — the previous context is bundled automatically
7. To give feedback: rate a diagram with stars and leave a comment

---

## Project structure

```
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI routers (auth, sessions, diagrams, feedback, websocket)
│   │   ├── core/         # Config, JWT auth, WebSocket connection manager
│   │   ├── models/       # SQLAlchemy ORM models
│   │   ├── schemas/      # Pydantic request/response + IR schemas
│   │   ├── services/     # Orchestrator, planner, validator, code gen, renderer, cache
│   │   └── prompts/      # System prompt, IR JSON schemas, few-shot examples
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── components/   # ChatPanel, DiagramPanel, FeedbackWidget, SessionSidebar
│       ├── hooks/        # useWebSocket
│       └── services/     # api.js (REST client)
├── docker-compose.yml
├── ARCHITECTURE.md       # Detailed architecture, all API contracts, interview Q&A
└── README.md
```

---

## API overview

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/auth/register` | Create account |
| POST | `/api/v1/auth/login` | Get JWT |
| POST | `/api/v1/sessions` | Create session |
| GET | `/api/v1/sessions` | List sessions |
| POST | `/api/v1/sessions/{id}/messages` | New generation (returns 202, streams via WS) |
| PUT | `/api/v1/sessions/{id}/messages/{id}` | Updated prompt |
| GET | `/api/v1/diagrams?message_id={id}` | Get generated diagrams |
| POST | `/api/v1/feedback` | Submit rating/feedback |
| WS | `/ws/stream/{message_id}?token={jwt}` | Real-time generation stream |

Full request/response contracts are in [`ARCHITECTURE.md`](./ARCHITECTURE.md).

---

## Known limitations

- Password hashing uses SHA-256 instead of bcrypt (passlib is installed but not wired up)
- SVG is injected via `dangerouslySetInnerHTML` without sanitization
- In-memory cache and WebSocket connection manager are not shared across instances (Redis would be needed for multi-instance)
- PlantUML DSL validation is structural only (`@startuml`/`@enduml` check) — full JAR-based syntax validation is not implemented
- LangChain ART feedback loop is a logging stub, not a live training pipeline
