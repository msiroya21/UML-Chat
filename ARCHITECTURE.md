# UML Chatbot — Architecture & Interview Prep

Natural language prompt → validated IR → PlantUML DSL → rendered SVG, streamed to the browser in real-time via WebSocket.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Component Map](#2-component-map)
3. [Startup & API Spin-up](#3-startup--api-spin-up)
4. [API Contracts](#4-api-contracts)
   - [Auth](#41-auth)
   - [Sessions](#42-sessions)
   - [Messages](#43-messages)
   - [Diagrams](#44-diagrams)
   - [Feedback](#45-feedback)
   - [WebSocket Protocol](#46-websocket-protocol)
5. [Generation Pipeline](#5-generation-pipeline)
6. [IR Abstraction Layer](#6-ir-abstraction-layer)
7. [Caching Strategy](#7-caching-strategy)
8. [Feedback & ART Loop](#8-feedback--art-loop)
9. [Probable Interview Questions](#9-probable-interview-questions)

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────┐
│  BROWSER                                                    │
│  React Frontend   ←─ WebSocket ─→   useWebSocket hook      │
│  (ChatPanel, DiagramPanel)          api.js (REST + JWT)     │
└────────────────────────┬────────────────────────────────────┘
                         │ REST /api/v1  │ WS /ws/stream/{id}
┌────────────────────────▼────────────────────────────────────┐
│  FASTAPI BACKEND                                            │
│  API Routers  →  BackgroundTasks  →  WS ConnectionManager  │
│  SQLAlchemy/aiosqlite (SQLite)                              │
└────────────────────────┬────────────────────────────────────┘
                         │ asyncio.gather (parallel per diagram type)
┌────────────────────────▼────────────────────────────────────┐
│  ORCHESTRATION LAYER                                        │
│  Planner → Validator → Repair Agent → Code Gen → Renderer  │
└──────────┬──────────────────────────────────────┬──────────┘
           │                                      │
    ┌──────▼──────┐                     ┌─────────▼─────────┐
    │  Groq API   │                     │ PlantUML Server   │
    │ Llama-3.3   │                     │ (Docker :8090)    │
    └─────────────┘                     └───────────────────┘
```

### Three User Scenarios

| Scenario | HTTP call | What happens |
|---|---|---|
| New user, new prompt | `POST /sessions/{id}/messages` | Full pipeline runs, results stream over WS |
| Existing user, updated prompt | `PUT /sessions/{id}/messages/{id}` | Bundles old + new prompt, re-runs pipeline, version increments |
| Existing user, feedback | `POST /feedback` | Stored in DB, forwarded to ART stub for RL training |

### Key Design Decisions

**Why WebSocket over polling?**
Pipeline takes 10–30s and produces multiple independent outputs. WS lets us push each diagram as it finishes rather than waiting for all. Polling at 2s intervals would be wasteful and still feel laggy.

**Why an IR layer instead of asking the LLM to output PlantUML directly?**
LLMs frequently produce subtly invalid DSL — mismatched lifeline names, undefined participants in fragments. Validating and repairing raw PlantUML strings requires regex heuristics or JVM overhead. The IR layer gives us a schema-validated JSON structure we can validate with Pydantic, repair semantically, and convert deterministically to DSL. It decouples "understanding intent" (LLM's job) from "correct syntax" (deterministic code gen's job).

**Why PlantUML server (Docker) over JAR?**
JAR requires a JVM in the Python container. The Docker-compose sidecar keeps the backend pure Python and keeps the JVM isolated.

**Why Groq?**
~700 tok/s vs ~60 tok/s on comparable GPU-based inference. IR generation is ~1–2s instead of 10–15s. The latency difference is the primary reason.

---

## 2. Component Map

### Backend — `backend/app/`

| File | Responsibility |
|---|---|
| `main.py` | App factory; `@asynccontextmanager` lifespan (DB init); CORS; router mounts |
| `api/auth.py` | `POST /register`, `POST /login`, returns JWT |
| `api/sessions.py` | Session CRUD + message CRUD + `BackgroundTasks` orchestrator trigger |
| `api/diagrams.py` | List diagrams, SVG/PNG export |
| `api/feedback.py` | Persist rating, forward to ART stub |
| `api/ws.py` | WebSocket endpoint, keep-alive receive loop |
| `services/orchestrator.py` | 7-step pipeline, `asyncio.gather`, WS broadcast |
| `services/planner.py` | LLM call → structured IR JSON |
| `services/validator.py` | Pydantic schema validation on IR |
| `services/repair_agent.py` | Re-prompt LLM with errors, up to 3 retries |
| `services/code_generator.py` | IR dict → PlantUML DSL string (deterministic) |
| `services/renderer.py` | HTTP GET to PlantUML server → SVG string |
| `services/cache.py` | SHA-256 keyed in-memory dict |
| `core/ws_manager.py` | `ConnectionManager`: `message_id → List[WebSocket]` |
| `core/config.py` | `pydantic-settings` Settings; reads `.env`; fail-fast on missing keys |
| `core/security.py` | `hash_password`, `verify_password`, `create_jwt`, `decode_jwt` |
| `core/dependencies.py` | `get_current_user` FastAPI dependency (injected into all protected routes) |
| `models/db.py` | SQLAlchemy ORM: `User`, `Session`, `Message`, `Diagram`, `Feedback` |

### Frontend — `frontend/src/`

| File | Responsibility |
|---|---|
| `App.jsx` | Auth gate, 3-panel layout shell |
| `components/ChatPanel.jsx` | Prompt input, diagram type chips (14 types), update/feedback mode toggle |
| `components/DiagramPanel.jsx` | SVG cards, zoom/pan, PlantUML code toggle, fallback badge |
| `components/FeedbackWidget.jsx` | 5-star rating, feedback type selector, comment |
| `components/SessionSidebar.jsx` | Session list, create, inline rename |
| `hooks/useWebSocket.js` | WS connect, frame dispatch by type |
| `services/api.js` | Fetch-based REST client with JWT header injection |

### Infrastructure

| File | Responsibility |
|---|---|
| `docker-compose.yml` | `plantuml/plantuml-server:jetty` on port 8090 |
| `backend/.env` | `GROQ_API_KEY`, `JWT_SECRET`, `DATABASE_URL`, `PLANTUML_SERVER_URL` |
| `backend/uml_chatbot.db` | SQLite file, auto-created on first startup via ORM |

---

## 3. Startup & API Spin-up

> The startup sequence has a dependency order. Do not skip steps.

### Step 1 — PlantUML sidecar (Docker)

```bash
docker-compose up -d
# Verify it's up:
curl http://localhost:8090/
```

The backend doesn't hard-fail if this is absent at startup — it only fails at render time. But start it first.

---

### Step 2 — Environment variables (Pydantic Settings)

`core/config.py` extends `pydantic_settings.BaseSettings`. On import it reads `backend/.env` and validates all fields. Missing required keys throw a `ValidationError` **before Uvicorn binds a port** — fail-fast at load time, not at first request.

Required keys in `backend/.env`:
```
GROQ_API_KEY=gsk_...
JWT_SECRET=your-secret-key-here
DATABASE_URL=sqlite+aiosqlite:///./uml_chatbot.db
PLANTUML_SERVER_URL=http://localhost:8090
LLM_MODEL=llama-3.3-70b-versatile
```

---

### Step 3 — FastAPI lifespan (DB init)

`main.py` uses `@asynccontextmanager` for the lifespan (the modern replacement for the deprecated `@app.on_event("startup")`). On startup it calls `init_db()` which runs `Base.metadata.create_all(engine)` asynchronously via aiosqlite. All five ORM tables are created idempotently — no migrations needed for SQLite.

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()   # creates tables if not exist
    yield
    # engine cleanup on shutdown

app = FastAPI(lifespan=lifespan)
```

If `init_db()` raises, the process exits before accepting requests. No route is ever callable before the DB is ready.

---

### Step 4 — CORS and router registration

CORS middleware is added **before** routers are included (FastAPI middleware ordering matters). The WebSocket router is mounted at root level, not under `/api/v1`, because browsers don't support custom headers on WS upgrade requests — auth is via query param `?token=`.

```python
app.add_middleware(CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"])

app.include_router(auth_router,     prefix="/api/v1/auth")
app.include_router(sessions_router, prefix="/api/v1/sessions")
app.include_router(diagrams_router, prefix="/api/v1/diagrams")
app.include_router(feedback_router, prefix="/api/v1/feedback")
app.include_router(ws_router)       # /ws/stream/{message_id}
```

---

### Step 5 — Start the backend

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

Swagger UI: `http://localhost:8000/docs`
WebSocket test: `ws://localhost:8000/ws/stream/{message_id}?token={jwt}`

---

### Step 6 — Start the frontend

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173
```

The Vite dev server calls `http://localhost:8000` directly — no proxy config. API base URL is set in `services/api.js`.

---

## 4. API Contracts

All endpoints under `/api/v1`. Protected routes require `Authorization: Bearer <jwt>`.

### 4.1 Auth

#### `POST /api/v1/auth/register` — public

```json
// Request
{
  "username": "manan",
  "email": "m@example.com",
  "password": "s3cur3pass"
}

// Response 201
{
  "user_id": "uuid-...",
  "username": "manan",
  "email": "m@example.com",
  "created_at": "2026-07-12T10:00:00Z"
}
```

Errors: `409` email already registered, `422` Pydantic validation failure.

---

#### `POST /api/v1/auth/login` — public

```json
// Request
{
  "email": "m@example.com",
  "password": "s3cur3pass"
}

// Response 200
{
  "token": "eyJhbGci...",   // HS256 JWT
  "expires_in": 86400,      // seconds
  "user": {
    "user_id": "uuid-...",
    "username": "manan",
    "email": "m@example.com"
  }
}
```

JWT payload contains `sub` (user_id) and `exp`. Decoded by `get_current_user` dependency injected into every protected route via FastAPI's `Depends()`.

---

### 4.2 Sessions

#### `POST /api/v1/sessions` — protected

```json
// Request
{ "title": "Compliance Monitor" }  // optional; LLM auto-generates if omitted

// Response 201
{
  "session_id": "uuid-...",
  "title": "Compliance Monitor",
  "user_id": "uuid-...",
  "created_at": "2026-07-12T10:00:00Z",
  "updated_at": "2026-07-12T10:00:00Z"
}
```

#### `GET /api/v1/sessions` — protected

Query params: `?page=1&limit=20`

```json
{
  "sessions": [ /* SessionResponse[] */ ],
  "total": 12,
  "page": 1,
  "pages": 1
}
```

#### `PATCH /api/v1/sessions/{session_id}` — protected

```json
// Request
{ "title": "New Title" }
// Response 200: updated SessionResponse
```

---

### 4.3 Messages

#### `GET /api/v1/sessions/{session_id}/messages` — protected

```json
{
  "messages": [{
    "message_id": "uuid-...",
    "session_id": "uuid-...",
    "prompt": "I am working on a compliance...",
    "diagram_types": ["sequence", "component"],
    "version": 1,
    "status": "complete",     // pending | generating | complete | error
    "parent_msg_id": null,
    "created_at": "2026-07-12T10:00:00Z"
  }]
}
```

---

#### `POST /api/v1/sessions/{session_id}/messages` — protected — **triggers WS**

> **Scenario 1: New user / new generation**

```json
// Request
{
  "prompt": "I am working on a compliance monitoring solution...",
  "diagram_types": ["sequence", "component", "class"]
  // diagram_types is optional — LLM auto-selects if omitted
}

// Response 202 — Accepted (generation runs in background)
{
  "message_id": "uuid-...",
  "session_id": "uuid-...",
  "version": 1,
  "status": "pending",
  "diagram_types": ["sequence", "component", "class"]
}
```

**Key:** Response returns immediately with `status: "pending"`. Client opens a WebSocket to `/ws/stream/{message_id}` to receive progress. HTTP 202 (not 200) because the work is accepted but not yet complete.

---

#### `PUT /api/v1/sessions/{session_id}/messages/{message_id}` — protected — **triggers WS**

> **Scenario 2: Existing user, updated prompt**

```json
// Request
{
  "prompt": "Now also add gap analysis against ISO 27001",
  "diagram_types": ["sequence", "class"]
}

// Response 202
// Same shape as POST, with version: 2, parent_msg_id: "{original_id}"
```

**What happens internally:** The handler fetches the original message, calls `process_prompt(new_prompt, old_prompt)` which produces a bundled prompt:

```
{old_prompt}

---

Updated requirements:
{new_prompt}
```

A new `Message` row is created with `version = old.version + 1` and `parent_msg_id` pointing to the original. Full pipeline re-runs on the bundled prompt. Original message and its diagrams are never modified — DB is append-only.

---

### 4.4 Diagrams

#### `GET /api/v1/diagrams?message_id={id}` — protected

```json
{
  "diagrams": [{
    "diagram_id": "uuid-...",
    "message_id": "uuid-...",
    "diagram_type": "sequence",
    "plantuml_code": "@startuml\n...\n@enduml",
    "svg": "<svg ...></svg>",
    "status": "complete",   // complete | error | fallback
    "error_msg": null,
    "created_at": "2026-07-12T10:00:00Z"
  }]
}
```

#### `GET /api/v1/diagrams/{diagram_id}/export?format=svg` — protected

Query param: `?format=svg` (default) or `?format=png`. Returns raw file bytes with appropriate `Content-Type`. PNG re-fetches from the PlantUML server using the stored `plantuml_code` at request time.

---

### 4.5 Feedback

#### `POST /api/v1/feedback` — protected

> **Scenario 3: Existing user, feedback**

```json
// Request
{
  "message_id": "uuid-...",
  "diagram_id": "uuid-...",      // optional — session-level feedback if omitted
  "rating": 4,                   // 1–5
  "feedback_type": "wrong_layout",
  "comment": "Missing the SEBI API box"
}

// Response 201
{ "feedback_id": "uuid-...", "status": "stored" }
```

Stored in `Feedback` table. `feedback_service.py` then calls `_log_art_sample_diagram()` which formats a DPO training sample and logs it. In production this would push to the LangChain ART training queue.

---

### 4.6 WebSocket Protocol

Connect immediately after receiving `message_id` from POST/PUT. Auth via query param (browser WS API doesn't support custom headers on upgrade).

```
ws://localhost:8000/ws/stream/{message_id}?token={jwt}
```

#### Frame types (server → client)

**`progress`** — emitted at each pipeline stage for each diagram type
```json
{
  "type": "progress",
  "diagram_type": "sequence",
  "stage": "generating_ir",
  "message": "Generating IR..."
}
```
Stages in order: `selecting_diagrams` → `generating_ir` → `validating` → `generating_code` → `validating_plantuml` → `rendering`

---

**`diagram_result`** — emitted when one diagram finishes (success or fallback)
```json
{
  "type": "diagram_result",
  "diagram_type": "sequence",
  "diagram_id": "uuid-...",
  "svg": "<svg...></svg>",
  "plantuml_code": "@startuml...",
  "status": "complete"
}
```
Diagrams arrive independently — frontend renders each as it arrives, not after all are done.

---

**`complete`** — emitted once all diagrams finish
```json
{
  "type": "complete",
  "message_id": "uuid-...",
  "total_diagrams": 3,
  "successful": 3
}
```
Safe to close the WS after this frame.

---

**`error`** — per-diagram error, pipeline continues for other types
```json
{
  "type": "error",
  "diagram_type": "class",
  "message": "Repair failed after 3 retries"
}
```

**ConnectionManager** (`core/ws_manager.py`): maintains a dict of `message_id → List[WebSocket]`. Multiple clients can watch the same generation. When the orchestrator calls `manager.broadcast(message_id, frame)`, all connected sockets receive it. Disconnected sockets are silently removed.

---

## 5. Generation Pipeline

Triggered via FastAPI `BackgroundTasks` immediately after message creation. HTTP response returns 202 before the pipeline starts.

```
POST /messages
    │
    ├── return 202 immediately (message_id in body)
    │
    └── BackgroundTasks.add_task(run_orchestrator, message_id)
            │
            ▼
        asyncio.gather(
            generate_one("sequence"),
            generate_one("component"),
            generate_one("class"),
        )
        # All diagram types run in parallel
        # Total latency ≈ slowest single diagram, not the sum
```

### Per-diagram steps

```
Step 1: Prompt Processing
    New message  → pass through
    Updated msg  → process_prompt(new, old) → bundled context string

Step 2: Diagram Selection
    User specified types  → validate against 14 known UML types
    No types specified    → ask LLM to recommend based on the prompt

Step 3: IR Generation (Groq LLM)  ← only LLM call in the happy path
    Input:  system_prompt.txt + JSON schema + few-shot examples + user prompt
    Output: structured JSON matching the IR schema for that diagram type
    Model:  llama-3.3-70b-versatile via Groq API (~700 tok/s)

Step 4: Validation + Repair Loop
    validate_ir() → Pydantic schema check on the LLM JSON output
    On failure → repair_agent() re-prompts with broken IR + error messages
    Up to 3 retries. If all fail → mark diagram "error", continue for others.

Step 5: Code Generation (deterministic, no LLM)
    ir_to_plantuml() converts validated IR dict → PlantUML DSL string
    Sequence: participants → messages → alt/loop fragments
    Class:    entities → attributes → methods → relationships
    Component: components → interfaces → dependencies
    Other types (activity, usecase, state): fallback to direct LLM DSL generation

Step 6: PlantUML Validation
    Structural check: starts with @startuml, ends with @enduml, ≥3 lines
    (Known gap: full JAR -syntax validation not implemented)

Step 7: SVG Rendering
    Encode DSL with PlantUML's custom base64 encoding
    HTTP GET → plantuml-server:8090/svg/{encoded}
    Store SVG in DB
    Broadcast diagram_result frame over WS
    On failure: store fallback SVG, broadcast error frame
```

**Why `BackgroundTasks` instead of returning the result synchronously?**
The pipeline takes 10–30s. Holding the HTTP connection open for that long means the client can't do anything else, connection timeouts are a risk, and the frontend can't show incremental progress. `BackgroundTasks` returns control to the client immediately, and WS handles the async result delivery.

---

## 6. IR Abstraction Layer

The Intermediate Representation (IR) is the architectural boundary between "what the LLM outputs" and "what gets rendered."

### Example: Sequence IR

```json
{
  "title": "SEBI Circular Ingestion",
  "participants": [
    { "name": "User",    "type": "actor" },
    { "name": "API",     "type": "participant" },
    { "name": "Parser",  "type": "participant" },
    { "name": "DB",      "type": "database" }
  ],
  "messages": [
    { "from": "User",   "to": "API",    "label": "GET /circulars", "type": "sync" },
    { "from": "API",    "to": "Parser", "label": "parse(raw)",     "type": "async" },
    { "from": "Parser", "to": "DB",     "label": "insert(clause)", "type": "sync" }
  ]
}
```

### Why IR instead of raw DSL output?

| Concern | Direct DSL | Via IR |
|---|---|---|
| Validation | Regex heuristics or JVM overhead | Pydantic schema — precise, fast |
| Error messages for repair | "Syntax error near line 7" | "Participant 'Scraper' used in message but not declared" |
| ART training signal | String diff of DSL | Structured JSON diff of IR — clean DPO (chosen/rejected) pairs |
| Adding a new diagram type | Prompt engineering for valid DSL | Add IR schema + code generator — orchestrator unchanged |

### IR schemas (`app/prompts/`)

- `ir_schema_sequence.json` — sequence diagram IR
- `ir_schema_class.json` — class diagram IR
- `ir_schema_component.json` — component diagram IR
- `schemas/ir.py` — Pydantic models: `SequenceDiagramIR`, `ClassDiagramIR`, `ComponentDiagramIR`

---

## 7. Caching Strategy

**In-memory SHA-256 cache** (`services/cache.py`)

Cache key = `SHA-256(prompt + diagram_type)`

Before calling Groq, the orchestrator checks the cache. A cache hit skips the entire LLM call + validation + code gen + render sequence.

```python
cache_key = sha256(f"{prompt}:{diagram_type}".encode()).hexdigest()
if cache_key in CACHE:
    return CACHE[cache_key]   # full result, no LLM call
# ... run pipeline ...
CACHE[cache_key] = result
```

**Trade-offs:**
- Cache is lost on process restart
- Not shared across instances (single-instance design)
- For production: Redis with TTL, keyed the same way

**Other latency optimizations:**
- `asyncio.gather` — all diagram types in parallel; latency = slowest single diagram
- Groq inference — ~700 tok/s vs ~60 tok/s on GPU inference
- Async throughout — `aiosqlite`, `httpx` async, no blocking I/O
- Early streaming — WS pushes each diagram result as it completes; user sees diagram 1 while 2 and 3 are still generating

---

## 8. Feedback & ART Loop

**Design intent: Direct Preference Optimization (DPO)**

When feedback arrives, the system constructs a DPO training sample:

```json
{
  "prompt": "<original user prompt>",
  "chosen":   { "ir": { /* high-rated IR, rating ≥ 4 */ }, "rating": 5 },
  "rejected": { "ir": { /* low-rated IR,  rating ≤ 2 */ }, "rating": 2 }
}
```

These (prompt, chosen, rejected) triples are the training signal for DPO — the model learns to increase the likelihood of generating IRs that look like `chosen` over `rejected` for the same prompt. LangChain's ART (Automated Reward Training) plugin would consume these samples to continuously fine-tune the Llama model's IR generation quality.

**Current state:** The logging stub in `feedback_service.py` is wired and formats the sample correctly. The actual ART training loop is not instantiated — it logs to stdout as a placeholder. In production it would push to a training queue (S3 bucket or message broker) that the ART trainer polls.

---

## 9. Probable Interview Questions

### System Design

**Q: Why WebSocket instead of HTTP polling or Server-Sent Events?**

Pipeline latency is 10–30s and produces multiple independent outputs (one per diagram type). Polling at 2s creates unnecessary server load and still feels laggy. SSE is unidirectional — fine for this use case, but WS is more natural for a chat interface where the client might need to send signals (e.g., cancellation). WS also lets the `ConnectionManager` support multiple concurrent watchers on the same `message_id` with no extra work.

---

**Q: Why an IR layer instead of asking the LLM to output PlantUML directly?**

LLMs frequently produce subtly invalid DSL — mismatched lifeline names, undefined participants in fragments, incorrect arrow syntax. Validating raw PlantUML requires running the JAR (JVM overhead) or regex heuristics that miss edge cases. The IR layer gives us a schema-validated JSON structure that we can validate with Pydantic in milliseconds, repair semantically ("participant X used but not declared" is a clear error message), and convert deterministically to DSL. It also decouples the LLM concern (understanding intent) from the rendering concern (correct syntax), making each independently improvable. The IR is also the correct unit for ART training — the model learns to produce better IR, not better DSL.

---

**Q: How do you handle diagram updates without losing history?**

Updated prompts create a new `Message` row with `version = previous.version + 1` and `parent_msg_id` pointing to the original. The original message and its diagrams are never modified. `process_prompt()` bundles the full previous context so the LLM has history without the frontend needing to manage message chaining. The DB is append-only — full audit trail of all generation attempts.

---

**Q: How is UML rendered? How do you control syntax errors?**

Rendering: PlantUML DSL is encoded using PlantUML's custom base64 encoding and sent as a URL path parameter to the Docker-hosted PlantUML server. The server returns SVG, which is stored in the DB and injected into the DOM.

Syntax control: The IR layer prevents most errors — since DSL is generated deterministically from validated IR, structural issues are caught at the IR validation step. The 3-retry repair loop handles the rest. DSL errors that slip through surface as a rendering failure from the PlantUML server, which triggers an `error` WS frame and a fallback SVG. Full JAR-based syntax validation (`plantuml.jar -syntax`) is a known gap — it would let us route DSL errors into the repair loop before the render step.

---

### API Spin-up

**Q: Walk me through spinning up the APIs properly, end to end.**

1. **Docker first:** `docker-compose up -d` starts the PlantUML server on port 8090. The backend won't crash without it but render calls fail — start it first.

2. **Config validation:** `core/config.py` uses `pydantic-settings`. On import it reads `backend/.env` and validates all required keys. Missing keys throw `ValidationError` before Uvicorn binds a port — you know immediately if config is broken.

3. **DB init on lifespan startup:** FastAPI's `@asynccontextmanager` lifespan calls `init_db()` which runs `Base.metadata.create_all()` via aiosqlite. All five tables created idempotently. No route is callable before the DB is ready. This is the modern replacement for the deprecated `@app.on_event("startup")`.

4. **CORS before routers:** CORS middleware is added before router includes — FastAPI applies middleware in registration order. WS router is at root level because browser WebSocket API doesn't support custom headers on upgrade; auth is `?token=` query param.

5. **`uvicorn app.main:app --reload --port 8000`** — Swagger at `/docs`.

6. **Frontend:** `npm run dev` in `frontend/`. Vite on port 5173 calls the backend directly at `localhost:8000`.

---

**Q: Why does POST /messages return 202 instead of 200?**

202 Accepted means "request has been accepted for processing but processing is not complete." The message row is created synchronously (so you get a `message_id`), but the generation pipeline runs via `BackgroundTasks` — it hasn't started yet when the HTTP response is sent. Using 200 would imply the work is done. 202 signals to the client: open your WebSocket connection now, results will stream. This is standard for async job submission APIs.

---

**Q: How does authentication work on WebSocket connections?**

The browser's native `WebSocket` API doesn't support custom headers on the upgrade request, so the standard `Authorization: Bearer` pattern doesn't work for WS. The solution is to pass the JWT as a query param: `ws://localhost:8000/ws/stream/{message_id}?token={jwt}`. The WS endpoint reads `token` from `query_params` and calls the same `decode_jwt()` function used by REST routes. Trade-off: the token appears in server logs. In production you'd use a short-lived WS-specific token issued immediately before the connection opens.

---

**Q: Why is the FastAPI lifespan pattern used?**

The `@asynccontextmanager` lifespan replaces the deprecated `@app.on_event("startup")` / `@app.on_event("shutdown")` decorators (deprecated in FastAPI 0.93+). Lifespan is more composable — it uses a standard Python context manager, easier to test by injecting a mock lifespan, and the startup/shutdown code is co-located in one function. If `init_db()` raises, the process exits before accepting requests. The old event-based approach made it possible for the app to start accepting requests before startup events completed in some edge cases.

---

### Scalability

**Q: What breaks first at scale? How would you fix it?**

| Bottleneck | Fix |
|---|---|
| In-memory cache (lost on restart, not shared) | Redis with TTL, same SHA-256 key |
| `BackgroundTasks` (runs in web server process) | Celery / ARQ task queue with Redis broker |
| WS `ConnectionManager` (in-memory dict, not shared) | Redis pub/sub — orchestrator publishes to per-`message_id` channel |
| SQLite (single writer) | PostgreSQL + asyncpg |
| Groq rate limits (unbounded LLM calls) | Semaphore or token bucket rate limiter on planner |

---

**Q: How do you minimize latency?**

- `asyncio.gather` — all diagram types run in parallel; 3 diagrams ≈ latency of the slowest one
- SHA-256 cache — identical prompts skip the entire pipeline
- Groq — ~700 tok/s inference vs ~60 tok/s on GPU-based providers
- Async throughout — no blocking I/O anywhere in the stack
- Early streaming — each diagram is pushed to the browser as it completes, not after all finish

---

### Implementation

**Q: How does the ART / RL feedback loop work?**

The design targets DPO (Direct Preference Optimization). Feedback submissions are structured as (prompt, chosen IR, rejected IR) triples where "chosen" comes from high-rated generations (≥4 stars) and "rejected" from low-rated ones (≤2 stars). The model learns to increase the likelihood of generating IRs that look like "chosen" over "rejected" for the same prompt. LangChain's ART plugin would consume these samples to fine-tune the base model. Current implementation: the sample is formatted and logged — the actual training queue is a stub.

---

**Q: You used an agentic coding tool for this round — how did you use it and how did you verify the output?**

I used Claude Code as the primary development agent. The workflow was: decompose the spec into phases (auth → session model → orchestrator → WS → frontend), prompt the agent with each phase with explicit acceptance criteria, then review every generated file before proceeding. Verification involved reading generated services end-to-end, checking correctness of async patterns (`asyncio.gather`, `BackgroundTasks`), and tracing the WebSocket message flow manually. I identified several bugs the agent introduced — SHA-256 instead of bcrypt for password hashing, unsanitized SVG injection, inverted ART training logic — demonstrating I understand the codebase, not just that I generated it.

---

**Q: What are the known gaps you'd fix before production?**

1. **Bcrypt:** Switch `security.py` from `hashlib.sha256` to `passlib.CryptContext` with bcrypt — SHA-256 with no salt is vulnerable to rainbow table attacks
2. **SVG sanitization:** Run SVG through DOMPurify before `dangerouslySetInnerHTML` injection to prevent XSS
3. **Diagram history:** Call `GET /diagrams?message_id=` on session load so previously generated diagrams are visible without regenerating — currently only live WS output persists in the UI
4. **Full PlantUML validation:** Run `java -jar plantuml.jar -syntax` to catch DSL errors before the render step, routing them into the repair loop
5. **Task queue:** Move `BackgroundTasks` to Celery/ARQ for production resilience
6. **Redis:** Replace in-memory cache and WS `ConnectionManager` with Redis-backed equivalents for multi-instance support
