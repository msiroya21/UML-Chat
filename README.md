# UML Chatbot

A chat platform that accepts a natural-language software design description and generates UML diagrams in real-time.

---

## What it does

- Describe a system in plain English → get rendered UML diagrams back, streamed to the browser as each one finishes.
- **14 diagram types**, in two tiers:
  - **7 full-IR types** — `sequence`, `class`, `component`, `activity`, `usecase`, `state`, `deployment` — go through a schema-validated Intermediate Representation with auto-repair.
  - **7 best-effort types** — `object`, `package`, `composite_structure`, `communication`, `interaction_overview`, `timing`, `profile` — the LLM emits PlantUML directly (shown with a β tag in the UI).
- **Iterative updates that only touch what changed.** Ask to "add a component diagram" and the existing diagrams are carried forward untouched; ask to "make the sequence async" and only that diagram regenerates. A failed regeneration keeps the previous good diagram (never overwrites it with a stub).
- **Feedback** — rate a diagram or leave a session-level suggestion; stored with generation provenance as durable training samples for a future RL/DPO loop.

### Input format

```json
{
  "prompt": "I am working on a compliance monitoring solution which will pull in the latest circulars from SEBI...",
  "diagram_types": ["sequence", "component", "class"]
}
```

`diagram_types` is optional — leave it empty and the backend auto-selects the most relevant types.

---

## Tech stack

| Layer | Stack |
|---|---|
| Frontend | React 19, Vite, plain CSS (no UI framework) |
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2.0 async, aiosqlite |
| LLM | Groq API — `llama-3.3-70b-versatile` (with model fallbacks) |
| LLM orchestration | LangChain 0.3 (`langchain-groq`) |
| Diagram rendering | PlantUML server (Docker) |
| Auth | JWT (PyJWT, HS256) |
| Realtime | WebSocket (FastAPI native) with frame buffering |
| DB | SQLite (file-based) + Alembic migrations |
| Tests | pytest |

---

## Architecture in brief

```
Browser (React)
    │  REST /api/v1              │  WebSocket /ws/stream/{message_id}
FastAPI Backend
    ├── create  → orchestrator (auto-select types → all "generate")
    └── update  → update planner:
                    diff requested vs. existing types
                    + LLM intent classifier (which existing diagrams to change)
                    → per-type action: generate | regenerate | carry_forward
            │
            └── asyncio.gather (Semaphore(4)) over the action plan
                    ├── Planner (Groq, JSON mode) → IR  [full-IR types]
                    │       or → PlantUML directly       [best-effort types]
                    ├── Validator (Pydantic) + Repair Agent (≤3 retries)
                    ├── Code Generator (IR → PlantUML DSL, deterministic)
                    └── Renderer (PlantUML server → SVG, detects error images)
```

**Key design decisions**
- **IR layer:** for the 7 core types the LLM outputs schema-validated JSON IR, not raw DSL; a deterministic generator converts IR → PlantUML. Validation, repair, and training signal are all cleaner on structured IR.
- **Storage = source of truth only:** each diagram stores `ir` + `plantuml_code`. SVG is **not** persisted — it's re-rendered from PlantUML on demand (live over WS, and when an old session is reopened).
- **Real syntax verification:** the renderer detects PlantUML error images (not just HTTP 200) and routes failures into the repair loop.

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the full breakdown, API contracts, and design rationale.

---

## Prerequisites

- Python 3.11+
- Node.js 18+
- Docker (for the PlantUML rendering server)
- A [Groq API key](https://console.groq.com) (free tier is sufficient)

---

## Quick start

### 1. Start the PlantUML server

```bash
docker compose up -d          # or: docker-compose up -d
```

Starts `plantuml/plantuml-server:jetty` on port 8090. The backend needs this to render diagrams.

### 2. Configure the backend

```bash
cd backend
cp .env.example .env
```

Edit `.env` and set at least `GROQ_API_KEY` and `JWT_SECRET`:

```
GROQ_API_KEY=your_groq_api_key_here
JWT_SECRET=any-long-random-string
LLM_MODEL=llama-3.3-70b-versatile
PLANTUML_SERVER_URL=http://localhost:8090
DATABASE_URL=sqlite+aiosqlite:///./uml_chatbot.db
```

### 3. Install backend deps and create the database

```bash
cd backend
pip install -r requirements.txt
alembic upgrade head           # creates the SQLite schema
```

> The schema is owned entirely by Alembic — the app does **not** auto-create tables on startup, so `alembic upgrade head` is **required** on a fresh checkout (and again after pulling new migrations). One source of truth, no `create_all`-vs-migration drift.

### 4. Start the backend

```bash
uvicorn app.main:app --reload --port 8000
```

Swagger UI: `http://localhost:8000/docs`.

### 5. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

---

## Usage

1. Register (or log in) — auth is minimal by design; any email/password works.
2. Create a session (auto-named from your first prompt).
3. Type a design description; pick diagram types with the chips (or **Select all** / **Clear** to auto-select).
4. Diagrams stream in as each finishes; failures show as an error card or a ⚠ Fallback (the model's real attempted code), never a fake example.
5. On any diagram card: **Show Code** (raw PlantUML), zoom, or **Rate**.
6. **Update** mode: send a follow-up prompt — only the diagrams your instruction targets regenerate; the rest are carried forward unchanged.
7. **Feedback** mode: leave a session-level suggestion that's stored as a training sample.
8. Reopen an old session anytime — prior diagrams are re-rendered from stored PlantUML (no regeneration).

---

## Testing

```bash
cd backend
python -m pytest tests/ -q
```

Covers the deterministic pieces that make the refactor safe: IR → PlantUML generators (all 7 types), IR validation (referential integrity), the update diff logic, and robust JSON extraction.

---

## Project structure

```
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI routers (auth, sessions, diagrams, feedback, ws)
│   │   ├── core/         # config, JWT, WS connection manager (with frame buffer)
│   │   ├── models/       # SQLAlchemy ORM (User, Session, Message, Diagram, Feedback, TrainingSample)
│   │   ├── schemas/      # Pydantic request/response + IR schemas
│   │   ├── services/     # orchestrator, planner, update_planner, llm_client,
│   │   │                 #   validator, repair_agent, code_generator, renderer, cache
│   │   └── prompts/      # system prompt, IR JSON schemas, few-shot examples
│   ├── alembic/          # migrations (initial schema)
│   ├── tests/            # pytest suite
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── components/   # ChatPanel, DiagramPanel, FeedbackWidget, SessionSidebar
│       ├── hooks/        # useWebSocket
│       └── services/     # api.js (REST client)
├── docker-compose.yml
├── ARCHITECTURE.md
└── README.md
```

---

## API overview

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/auth/register` | Create account → JWT |
| POST | `/api/v1/auth/login` | Log in → JWT |
| POST | `/api/v1/sessions` | Create session |
| GET | `/api/v1/sessions` | List sessions |
| PATCH | `/api/v1/sessions/{id}` | Rename session |
| GET | `/api/v1/sessions/{id}/messages` | List messages (with status) |
| POST | `/api/v1/sessions/{id}/messages` | New generation (202, streams via WS) |
| PUT | `/api/v1/sessions/{id}/messages/{mid}` | Updated prompt (diff + carry-forward) |
| GET | `/api/v1/sessions/{id}/messages/{mid}/diagrams` | Diagrams for a turn (SVG re-rendered on demand) |
| POST | `/api/v1/feedback` | Submit rating/feedback |
| WS | `/ws/stream/{message_id}` | Real-time generation stream |

Full request/response contracts are in [`ARCHITECTURE.md`](./ARCHITECTURE.md).

---

## Design notes & tradeoffs

These are the choices made knowingly — what was traded away, and why. Grouped by intent.

### 🟢 Deliberate tradeoffs (a drawback we chose on purpose)

- **Snapshot storage.** Each turn owns a full set of diagram rows; a diagram carried forward unchanged is *copied* into the new turn. This duplicates `ir`/`plantuml_code` across versions, but every turn is self-contained and answerable with a single `WHERE message_id = ?` — no version-walking to render an old turn. (At real scale you'd store each diagram body once and reference it by hash.)
- **`Diagram.version` is denormalized.** Version really belongs to the turn (`Message.version`), but it's copied onto each diagram so a diagram row stands alone. It can't drift today (always written from the message), and it keeps the snapshot self-contained.
- **One diagram is committed at a time (no turn-level atomicity).** Diagrams are generated in parallel and each is persisted the moment it's ready, so the UI can stream them in as they finish. The cost: a turn can be partially complete if the process dies mid-run — which is exactly what the `Message.status` (`processing`/`complete`/`failed`) column makes visible.
- **PlantUML validity is verified by *rendering*, not by string checks.** The structural check (`validate_plantuml`) is intentionally shallow; the real gate is detecting the PlantUML server's error image after an actual render. That's slower but it's true verification, and syntax errors feed the repair loop.
- **LLM calls are synchronous, run on a thread pool.** The Groq calls use LangChain's sync client offloaded via `run_in_executor`, kept simple and correct rather than fully async. Combined with the concurrency throttle below, it's more than enough for the workload.
- **The result cache is in-process and cross-user.** Keyed by `(prompt, diagram_type)` — a deterministic function of the input, so sharing across users leaks nothing. It's bounded (LRU) and never caches a fallback, so a transient failure can't be served forever.

### 🟡 Known limitations (fine at this scale — here's the scale-up path)

- **Requested vs. produced types can differ.** The chips record what you *asked for*; the actual diagrams are the rows that generated. If a type fails, you'll see the request tag but no diagram. At scale, derive the tag list from the produced rows.
- **LLM concurrency is a single global throttle.** A process-wide `Semaphore(4)` protects the Groq rate limit, so one user's large request can queue another's behind the same 4 slots. At scale, replace it with a per-API-key rate limiter / job queue.
- **Conversation memory grows unbounded.** Each turn re-sends the full prompt history so the model never forgets earlier requirements. A very long session therefore sends an ever-larger (and costlier) context. At scale, roll up older turns into a running summary and keep only the last few verbatim.
- **No sweeper for stuck runs.** If the process is killed mid-generation, that turn stays `processing` forever. The status column makes it visible; a periodic reaper (or a startup sweep) would flip abandoned runs to `failed`.

### ⚪ Deferred (out of scope for this build)

Security hardening is intentionally not done here:

- **Auth is minimal:** passwords are SHA-256 (not bcrypt/argon2), no rate limiting, no JWT refresh/revocation.
- **The WebSocket endpoint is unauthenticated** and `GET .../diagrams/{id}` has an IDOR — anyone with a `message_id`/`diagram_id` could read a diagram. Fine for local dev; must be fixed before any real deployment.
- **Secrets:** rotate `GROQ_API_KEY` / `JWT_SECRET` and keep `.env` and `uml_chatbot.db` out of version control before sharing.
- **Single-instance:** the in-memory cache and WS connection manager aren't shared across workers (Redis would be needed for multi-instance).
- **Best-effort types:** the 7 non-IR types depend on the LLM producing sound PlantUML; quality varies (especially `timing`).
- **Feedback loop:** feedback is collected as correct, durable training samples (with real user + generation provenance, and query-able `signal`/`diagram_type` columns) but is not yet wired back into generation (no live trainer).
