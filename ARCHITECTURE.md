# UML Chatbot — Architecture & Interview Prep

Natural-language prompt → validated IR → PlantUML DSL → rendered SVG, streamed to the browser in real-time over WebSocket. Updates are incremental (diff + carry-forward), and the data layer is designed for a single, clean query path.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Component Map](#2-component-map)
3. [Startup & API Spin-up](#3-startup--api-spin-up)
4. [API Contracts](#4-api-contracts)
5. [Generation Pipeline](#5-generation-pipeline)
6. [Update Semantics (diff + carry-forward)](#6-update-semantics-diff--carry-forward)
7. [IR Abstraction Layer](#7-ir-abstraction-layer)
8. [Data Layer](#8-data-layer)
9. [Memory & Conversation Context](#9-memory--conversation-context)
10. [Caching Strategy](#10-caching-strategy)
11. [Feedback & Training Data](#11-feedback--training-data)
12. [Interview Q&A](#12-interview-qa)

---

## 1. System Overview

```
┌───────────────────────────────────────────────────────────────┐
│  BROWSER (React)                                               │
│  ChatPanel · DiagramPanel · SessionSidebar                    │
│  useWebSocket hook          api.js (REST + JWT)               │
└───────────────┬───────────────────────────┬───────────────────┘
                │ REST /api/v1               │ WS /ws/stream/{id}
┌───────────────▼───────────────────────────▼───────────────────┐
│  FASTAPI BACKEND                                              │
│  routers → BackgroundTasks → WS ConnectionManager (buffered) │
│  SQLAlchemy 2.0 async / aiosqlite (+ Alembic)                │
└───────────────┬───────────────────────────────────────────────┘
                │ asyncio.gather over an action plan, Semaphore(4)
┌───────────────▼───────────────────────────────────────────────┐
│  ORCHESTRATION                                                │
│  update_planner → planner → validator → repair → codegen →    │
│  renderer (syntax-error detection)                            │
└──────────┬────────────────────────────────────────┬──────────┘
           │                                        │
    ┌──────▼──────┐                        ┌────────▼────────┐
    │  Groq API   │ (llm_client:           │ PlantUML Server │
    │  Llama-3.3  │  central fallback +     │ (Docker :8090)  │
    └─────────────┘  error taxonomy)       └─────────────────┘
```

### Three user scenarios

| Scenario | HTTP call | What happens |
|---|---|---|
| New user, new prompt | `POST /sessions/{id}/messages` | Auto-select types if none given; full pipeline per type; results stream over WS |
| Existing user, updated prompt | `PUT /sessions/{id}/messages/{mid}` | **Diff + intent routing**: only new/targeted types (re)generate; unchanged diagrams carried forward |
| Existing user, feedback | `POST /feedback` | Stored (anchored to a message) + a durable, attributable training sample |

### Key design decisions

- **IR layer** for the 7 core types: the LLM outputs schema-validated JSON, not raw DSL, so validation/repair/training are clean and deterministic code-gen owns syntax.
- **Snapshot + render-on-open storage:** persist `ir` + `plantuml_code` only. SVG is re-rendered from PlantUML on demand — no large derived blobs in the DB.
- **Incremental updates:** an update never blindly re-runs everything; it computes a per-type action plan and carries unchanged diagrams forward. A failed regeneration keeps the prior good diagram.
- **Central LLM client** (`llm_client.py`) with an error taxonomy: a bad API key fails loudly; transient 503s fall back across models; parse errors are handled — no silently-fabricated "example" diagrams.
- **Real syntax verification:** the renderer detects PlantUML error images and feeds them into the repair loop.

---

## 2. Component Map

### Backend — `backend/app/`

| File | Responsibility |
|---|---|
| `main.py` | App factory; `@asynccontextmanager` lifespan (DB init); CORS; router mounts |
| `api/auth.py` | `POST /register`, `POST /login` → JWT |
| `api/sessions.py` | Session CRUD, message create/update, lineage walk + prior-diagram snapshots for updates |
| `api/diagrams.py` | List diagrams (SVG re-rendered on demand), SVG/PNG export |
| `api/feedback.py` | Persist feedback, existence checks |
| `api/ws.py` | WebSocket endpoint, keep-alive receive loop |
| `services/orchestrator.py` | Action-plan pipeline, `asyncio.gather` + `Semaphore(4)`, WS broadcast, upserts, `run_update_background` |
| `services/update_planner.py` | LLM intent classifier + `compute_update_actions` (generate/regenerate/carry_forward) |
| `services/planner.py` | LLM → IR JSON (JSON mode) or direct PlantUML; `prior_ir` edit mode; raises typed errors (no example fallback) |
| `services/llm_client.py` | `invoke_with_fallback` (model fallback), `extract_json`, `LLMConfigError` / `LLMUnavailableError` |
| `services/validator.py` | Pydantic IR validation + structural PlantUML check |
| `services/repair_agent.py` | Re-prompt LLM with errors (≤3 retries) |
| `services/code_generator.py` | IR dict → PlantUML DSL (deterministic) for all 7 IR types |
| `services/renderer.py` | PlantUML server → SVG; **detects error images**; shared httpx client |
| `services/cache.py` | Bounded LRU (`ir` + `plantuml_code`); never caches fallbacks |
| `services/prompt_processor.py` | `build_context` — full-history context from the message chain |
| `services/title_generator.py` | Session auto-title (LLM + heuristic fallback) |
| `services/feedback_service.py` | Store feedback + build/persist training samples |
| `core/ws_manager.py` | `ConnectionManager`: `message_id → List[WebSocket]` + per-message frame buffer (replay on connect) |
| `core/config.py` | `pydantic-settings`; `GROQ_API_KEY`, `LLM_MODEL`, `LLM_FALLBACK_MODELS`, … |
| `core/security.py` | `hash_password`, `verify_password`, `create_jwt`, `decode_jwt` |
| `core/dependencies.py` | `get_current_user` FastAPI dependency |
| `models/db.py` | ORM: `User`, `Session`, `Message`, `Diagram`, `Feedback`, `TrainingSample`; SQLite PRAGMAs |
| `alembic/` | Migrations (initial schema) |

### Frontend — `frontend/src/`

| File | Responsibility |
|---|---|
| `App.jsx` | Auth gate; drives the diagram panel via a `view` = live (WS) or history (REST re-hydration) |
| `components/ChatPanel.jsx` | Prompt input, type chips + Select all/Clear, Update/Feedback mode, restores `lastMessageId` from history |
| `components/DiagramPanel.jsx` | Live WS stream **or** re-hydrated history; SVG via `data:` URI `<img>`; fallback badge + error banner |
| `components/FeedbackWidget.jsx` | Star rating, type selector, comment |
| `components/SessionSidebar.jsx` | Session list, create, inline rename |
| `hooks/useWebSocket.js` | WS connect, frame dispatch by type |
| `services/api.js` | Fetch REST client with JWT injection |

### Infrastructure

| File | Responsibility |
|---|---|
| `docker-compose.yml` | `plantuml/plantuml-server:jetty` on port 8090 |
| `backend/.env` | `GROQ_API_KEY`, `JWT_SECRET`, `DATABASE_URL`, `PLANTUML_SERVER_URL`, `LLM_MODEL` |
| `backend/uml_chatbot.db` | SQLite file (Alembic-managed; app also create_all on first run) |

---

## 3. Startup & API Spin-up

> Dependency order matters — don't skip steps.

**Step 1 — PlantUML sidecar:** `docker compose up -d` → server on 8090. The backend doesn't hard-fail without it; render calls fail until it's up.

**Step 2 — Config (Pydantic Settings):** `core/config.py` reads `backend/.env` on import. Missing/blank `GROQ_API_KEY` doesn't crash boot — instead the central `llm_client` raises `LLMConfigError` at call time, surfaced to the user as a clear config error rather than a fake diagram.

**Step 3 — Schema:** `alembic upgrade head` creates the schema. For convenience the FastAPI lifespan also runs `init_db()` (`Base.metadata.create_all`, idempotent) so a fresh dev run works without Alembic. SQLite connections get `PRAGMA foreign_keys=ON`, WAL, and `busy_timeout` via a connect-event listener (FK enforcement + parallel-write friendliness).

**Step 4 — CORS + routers:** CORS middleware is registered before routers. Routers mount under `/api/v1` (auth, sessions, diagrams, feedback); the WS router mounts at root (`/ws/stream/{message_id}`).

**Step 5 — Backend:** `uvicorn app.main:app --reload --port 8000` (Swagger at `/docs`).

**Step 6 — Frontend:** `npm run dev` in `frontend/` (Vite on 5173; API base is hard-coded to `localhost:8000` in `services/api.js`).

---

## 4. API Contracts

All under `/api/v1`; protected routes require `Authorization: Bearer <jwt>`.

### 4.1 Auth

```jsonc
// POST /api/v1/auth/register        // public
// Request
{ "email": "m@example.com", "password": "s3cur3pass", "name": "Manan" }
// Response 201
{ "user_id": "uuid-...", "token": "eyJhbGci..." }
```

```jsonc
// POST /api/v1/auth/login           // public
// Request  { "email": "m@example.com", "password": "s3cur3pass" }
// Response 200  { "user_id": "uuid-...", "token": "eyJhbGci..." }
```

JWT payload: `sub` (user_id) + `exp`. Decoded by the `get_current_user` dependency.

### 4.2 Sessions

```jsonc
// POST /api/v1/sessions             { "title": "..." }  // title optional -> "New Session", auto-titled on first prompt
// -> 201 { "session_id", "created_at", "title" }

// GET  /api/v1/sessions?page=1&per_page=50
// -> { "sessions": [ { "session_id", "created_at", "title" } ] }

// PATCH /api/v1/sessions/{id}       { "title": "New Title" }  -> 200 SessionResponse
```

### 4.3 Messages

```jsonc
// GET /api/v1/sessions/{id}/messages
// -> { "messages": [ { "message_id", "prompt", "diagram_types", "version", "status", "created_at" } ] }
//    status: processing | complete | failed
```

```jsonc
// POST /api/v1/sessions/{id}/messages         // Scenario 1 — triggers WS
// Request  { "prompt": "...", "diagram_types": ["sequence","class"] }   // diagram_types optional
// Response 202  { "message_id", "status": "processing", "ws_url": "/ws/stream/{message_id}" }
```

```jsonc
// PUT /api/v1/sessions/{id}/messages/{mid}     // Scenario 2 — triggers WS
// Request  { "prompt": "also add a component diagram", "diagram_types": ["sequence","class","component"] }
// Response 202  { "message_id", "version": 2, "status": "processing", "ws_url": "/ws/stream/{message_id}" }
```

On update the handler creates a new `Message` (`version+1`, `parent_msg_id` → previous), walks the `parent_msg_id` lineage to build full-history context, snapshots the previous turn's diagrams, and dispatches `run_update_background` (which classifies + builds the action plan). See §6.

### 4.4 Diagrams

```jsonc
// GET /api/v1/sessions/{id}/messages/{mid}/diagrams
// -> [ { "diagram_id", "diagram_type", "plantuml_code", "svg", "ir",
//        "is_valid", "is_fallback", "version" } ]
//    svg is RE-RENDERED from plantuml_code at request time (not stored).

// GET /api/v1/sessions/{id}/messages/{mid}/diagrams/{diagram_id}?format=svg|png
// -> raw file bytes (rendered from stored plantuml_code)
```

### 4.5 Feedback

```jsonc
// POST /api/v1/feedback              // Scenario 3
// Request (at least one of diagram_id / message_id required)
{ "diagram_id": "uuid-...", "rating": 5, "feedback_type": "praise", "feedback_text": "great" }
// Response 201  { "feedback_id": "uuid-...", "status": "accepted" }
```

The stored row **always** has `message_id` (derived from `diagram_id` when only that is given) → single join path. See §8 and §11.

### 4.6 WebSocket protocol

Connect to `ws://localhost:8000/ws/stream/{message_id}` right after the 202. Frames broadcast before the socket connects are **buffered and replayed on connect** (no lost early frames).

> **Auth note:** the WS endpoint is currently **unauthenticated** (a deferred security item). Intended design is a `?token={jwt}` query param (browsers can't set headers on WS upgrade) verified with the same `decode_jwt`.

Server → client frames:

```jsonc
// progress — per stage, per diagram type
{ "type": "progress", "diagram_type": "sequence", "stage": "generating_ir", "percent": 40 }
// stages: selecting_diagrams(10) -> generating_ir(40) -> validating_ir(60)
//         -> generating_plantuml(75) -> rendering_svg(90)

// diagram_result — one per finished diagram (success, carried-forward, or shown-invalid)
{ "type": "diagram_result", "diagram_id": "uuid", "diagram_type": "sequence",
  "plantuml_code": "@startuml...", "svg": "<svg...>", "ir": { },
  "is_fallback": false, "validation": { "is_valid": true, "errors": [], "warnings": [] } }

// complete — once the run finishes
{ "type": "complete", "diagrams_generated": 3, "total_time_ms": 8421 }

// error — a diagram failed with no salvageable code
{ "type": "error", "diagram_type": "class", "error_code": "GENERATION_FAILED",
  "message": "...", "partial_code": null }
```

`ConnectionManager` maps `message_id → List[WebSocket]`; multiple clients can watch one generation; the per-message buffer is dropped after `complete`.

---

## 5. Generation Pipeline

Triggered via `BackgroundTasks` after the 202. `run_orchestrator_background` builds specs (create path: auto-select → all `generate`) or receives a prebuilt action plan (update path). Each spec runs through `process_single_diagram` under a `Semaphore(4)`.

### Per-diagram steps

```
carry_forward  → copy the prior diagram row (ir + plantuml) to the new turn,
                 re-render SVG, broadcast. No LLM.

generate / regenerate:
  1. Cache check (fresh generate only)
  2. IR generation (Groq, JSON mode)          [full-IR types]
       or direct PlantUML                       [best-effort types]
       - prior_ir given (regenerate) -> edit the existing IR
       - LLMConfigError -> loud CONFIG_ERROR frame (not a stub)
  3. Validate IR (Pydantic) + repair loop (≤3)  [IR types]
  4. IR -> PlantUML DSL (deterministic)
  5. Structural DSL check
  6. Render -> SVG; DETECT PlantUML error image
       - error + IR type + retries left -> repair and re-render
  7. Success -> cache (source of truth) + upsert Diagram + broadcast diagram_result
       Failure -> see below
```

**On failure** (`_handle_failure`): if this was a *regeneration* and a prior good diagram exists → **carry the prior forward** (no-stub-overwrite). Otherwise persist + broadcast the model's **real attempted PlantUML** as `is_valid=false, is_fallback=true` (the UI shows the code + an error banner). Only if there's nothing salvageable is a bare `error` frame sent. No fabricated example diagram, ever.

Writes are **upserts** keyed on `(message_id, diagram_type)` (the unique constraint), so retries/re-dispatch never duplicate rows.

---

## 6. Update Semantics (diff + carry-forward)

The behavior a reviewer will poke at: "if I ask to add a component, do the other diagrams get destroyed?" No.

```
requested types        = what the update selected  (e.g. [sequence, class, component])
prev_good_types        = types with a valid, non-fallback diagram on the previous turn
targeted               = classify_update_targets(update_text, prev_good_types)   # small LLM call

for each requested type t:
    t not in prev_good_types      -> generate       (brand-new type)
    t in targeted                 -> regenerate      (edit prior IR)
    otherwise                     -> carry_forward   (copy prior, no LLM)
prev types not requested          -> dropped
```

- "**also add a component**" → `component` generates; `sequence`, `class` carried forward byte-identical.
- "**make the sequence async**" → classifier targets `sequence` → only it regenerates (from prior IR); others carried forward.
- Classification failure defaults to "targets nothing" (safe: carry everything forward rather than risk a destructive regen).

The classifier runs in the **background** (an LLM call), not in the request handler, so the `PUT` still returns 202 fast.

---

## 7. IR Abstraction Layer

The IR is the boundary between "what the LLM understands" and "what renders."

- **7 full-IR types** (`IR_SCHEMA_MAP`): `sequence`, `class`, `component`, `activity`, `usecase`, `state`, `deployment`. Each has a Pydantic model with a `@model_validator` enforcing referential integrity (every edge/message/relationship endpoint must resolve to a declared node), a deterministic generator in `code_generator.py`, and a few-shot example in `prompts/few_shot_examples/`.
- **7 best-effort types**: `object`, `package`, `composite_structure`, `communication`, `interaction_overview`, `timing`, `profile`. The LLM emits PlantUML directly (guided by a per-type snippet); output is sanitized to a clean `@startuml…@enduml` block. No structured validation/repair — flagged β in the UI.

Example — sequence IR:

```json
{
  "diagram_type": "sequence", "title": "SEBI Circular Ingestion",
  "participants": [ { "id": "u", "label": "User", "type": "actor" },
                    { "id": "api", "label": "API", "type": "participant" } ],
  "messages": [ { "from": "u", "to": "api", "label": "GET /circulars", "type": "sync", "order": 1 } ],
  "fragments": []
}
```

Why IR over raw DSL: Pydantic validation is precise and fast; repair errors are semantic ("participant 'X' used but not declared"); adding a type = schema + generator, orchestrator unchanged; and the IR is the right unit for training signal.

---

## 8. Data Layer

The schema is designed so common queries are a **single join**, and stored data is the source of truth only.

### Tables

- **User** → **Session** (`user_id`) → **Message** (`session_id`) → **Diagram** (`message_id`).
- **Message**: one user turn. `version` + `parent_msg_id` model lineage (the chain is walked for context and carry-forward); `status` (processing/complete/failed) makes a crashed generation visible; `diagram_types` is *requested* metadata only (the produced set is the Diagram rows). No `role` column (all turns are user turns; the assistant output is diagrams).
- **Diagram**: `ir` + `plantuml_code` (**no `svg`** — re-rendered on demand), truthful `is_valid` / `is_fallback`, provenance `model` + `prompt_version`, `version`. `UniqueConstraint(message_id, diagram_type)` → upserts, no duplicates.
- **Feedback**: **always anchored to `message_id`** (single join path); `diagram_id` is an optional *refinement*, not a second parent. Both `Message.feedbacks` and `Diagram.feedbacks` relationships exist. Cascades on delete.
- **TrainingSample**: durable ART/DPO samples with the real `user_id`, `scope`, and generation provenance (replaces logging to stdout).

### Versioning / storage model — *snapshot + render-on-open*

Each turn owns a **full set** of Diagram rows; carried-forward diagrams are copied. Only `ir` + `plantuml_code` are stored; SVG is re-rendered from PlantUML when needed (live over WS, and on session re-open via `GET .../diagrams`). Trade-off consciously accepted: `ir`/`plantuml_code` are duplicated across versions in exchange for immutable per-version snapshots and dead-simple `WHERE message_id` queries.

### Integrity

`PRAGMA foreign_keys=ON` (SQLite ignores FKs otherwise) + `ondelete="CASCADE"`; WAL + `busy_timeout` for the parallel fan-out writes; composite indexes matching the actual sort paths (`messages(session_id, created_at)`, `sessions(user_id, updated_at)`); timezone-aware UTC timestamps. Schema evolution is via **Alembic** (initial migration checked in).

---

## 9. Memory & Conversation Context

`build_context(prompts)` assembles the **full** conversation from the ordered `parent_msg_id` lineage — original requirements + each update + the current instruction — so context never collapses to a single turn (the earlier one-level bundle dropped the original prompt after two updates). On the client, `ChatPanel` restores `lastMessageId` from loaded history so a follow-up after a page reload is correctly treated as an **update**, and `DiagramPanel` re-hydrates prior diagrams from the DB. Regeneration additionally passes the previous diagram's `ir` to the planner (edit mode) for consistent refinements.

---

## 10. Caching Strategy

Bounded in-memory **LRU** (`services/cache.py`), keyed `sha256(prompt_context + ":" + diagram_type)`, storing `{ir, plantuml_code}` (not SVG). A cache hit skips the LLM + validation + code-gen. **Fallbacks are never cached** — otherwise a transient outage would be served forever. Documented single-process trade-off (Redis for multi-instance).

Other latency levers: `asyncio.gather` (parallel per type; wall-clock ≈ slowest), `Semaphore(4)` to avoid Groq rate-limit bursts, Groq's fast inference, async I/O throughout, and early WS streaming (each diagram shown as it finishes).

---

## 11. Feedback & Training Data

Feedback is stored and turned into a **correct, attributable** training sample (`TrainingSample` table):

```json
{
  "user_id": "<real user id>",
  "input": { "prompt": "<message prompt>", "diagram_types": ["sequence","class"] },
  "diagram": { "diagram_type": "sequence", "ir": { }, "model": "llama-3.3-70b-versatile", "prompt_version": "2026-07-14" },
  "signal": "chosen",         // rating >= 4 -> chosen, < 3 -> rejected, else neutral
  "feedback": { "type": "praise", "rating": 5, "text": "great", "corrections": null },
  "timestamp": "2026-07-14T..."
}
```

This fixes an earlier bug where the "user" field was `sha256(diagram_id)` (the diagram id mislabeled as the user) and samples were only logged. The intent is DPO: (prompt, chosen IR, rejected IR) triples that a trainer increases/decreases likelihood on. **Deferred:** wiring these back into generation (a live trainer) is out of scope for this build — the data is collected correctly, not yet consumed.

---

## 12. Interview Q&A

### Using the AI tool — and challenging its decisions

**Q: You built this with an agentic coding tool. How did you use it, and how do you know it's not just "something that works"?**

Claude Code was the primary implementer; my job was to interrogate its granular decisions, not just accept passing behavior. A first pass "worked" but I found and fixed a series of decisions a careful engineer should challenge:

- **Feedback schema (the one you flagged):** it modeled feedback with two nullable parents (`diagram_id` OR `message_id`) — a polymorphic-parent anti-pattern forcing UNION queries. Reworked so feedback is always anchored to `message_id` with `diagram_id` as a refinement → one join path.
- **"Syntax verification" was a facade:** the renderer treated any HTTP 200 as success, but PlantUML returns 200 with an *error image*. Now the renderer detects error responses and routes them into the repair loop.
- **Silent example fallbacks:** on any LLM hiccup it rendered a few-shot *example* as if it were the user's diagram. Now failures surface the model's real attempted code (flagged) or a clear error — never a fake.
- **Mislabeled training data:** the "user_hash" in the ART sample was `sha256(diagram_id)` — the diagram id, not the user. Fixed to the real `user_id` + generation provenance, persisted durably.
- **Update destroyed good diagrams:** an update re-ran every selected type from scratch; a single transient failure replaced a good diagram with a stub. Now updates diff + carry forward, and a failed regen keeps the prior good one.
- Plus: unbounded in-memory cache (bounded + never caches fallbacks), a blocking LLM call on the event loop (offloaded), storing SVG in the DB (dropped for render-on-open), a dead `role` column and double lineage (removed), duplicated fragile model-fallback code (centralized in `llm_client`).

### System design

**Q: Why WebSocket over polling/SSE?** The pipeline is ~10s and produces multiple independent outputs; WS pushes each diagram as it finishes. WS also lets multiple clients watch one `message_id` and supports client→server signals. Early frames survive the connect race via a per-message buffer.

**Q: Why an IR layer?** LLMs produce subtly invalid DSL. Schema-validated JSON IR lets us validate in ms with Pydantic, repair with semantic error messages, and generate DSL deterministically — decoupling "intent" from "syntax," and giving a clean training unit. Applied to the 7 core types; the other 7 are honest best-effort direct-PlantUML.

**Q: How are updates handled without losing history or clobbering diagrams?** New `Message` per turn (`version+1`, `parent_msg_id`). An update computes a per-type action plan (generate / regenerate / carry_forward) using a diff plus an LLM intent classifier; unchanged diagrams are carried forward; a failed regeneration keeps the prior good diagram. The DB is append-only per turn.

**Q: How is UML rendered and how do you control syntax errors?** DSL is base64-encoded (PlantUML's scheme) and GET to the Docker server → SVG. Most errors are prevented by deterministic gen from validated IR; the repair loop handles the rest; and the renderer now catches PlantUML *error images* (real syntax verification) and re-repairs. SVG is rendered on demand, not stored, and displayed via a `data:` URI `<img>` (no `dangerouslySetInnerHTML`).

**Q: How do you minimize latency?** Parallel `asyncio.gather` (wall-clock ≈ slowest diagram), a bounded cache for identical prompts, Groq's fast inference, async I/O throughout, early WS streaming, and carry-forward (unchanged diagrams skip the LLM entirely on updates).

### Spin-up & correctness

**Q: Why 202 on POST /messages?** The message row is created synchronously (you get a `message_id` + `ws_url`), but generation runs in `BackgroundTasks`. 202 = "accepted, not complete" — open the WS for results.

**Q: What happens if the API key is missing/invalid?** `llm_client` raises `LLMConfigError`; the orchestrator emits a `CONFIG_ERROR` frame instead of a fake diagram. Transient 503s fall back across `LLM_FALLBACK_MODELS`.

**Q: How does an old session show its diagrams again?** `ChatPanel` restores `lastMessageId` and `DiagramPanel` calls `GET .../diagrams`, which re-renders SVG from stored `plantuml_code` (no LLM, sub-second). No regeneration.

### Scalability

| Bottleneck | Fix |
|---|---|
| In-memory cache / WS manager (per-process) | Redis (cache with TTL; pub/sub for WS fan-out) |
| `BackgroundTasks` in the web process | Celery / ARQ + broker |
| SQLite single writer | PostgreSQL + asyncpg (Alembic already in place) |
| Groq rate limits | `Semaphore(4)` today; token-bucket limiter for scale |

### Known gaps to close before production

1. **Security (all deferred):** bcrypt/argon2 passwords, authenticate the WS endpoint, fix the `get_diagram_file` IDOR + feedback ownership checks, rate limiting, JWT refresh/revocation, stop committing `.env`/DB and rotate secrets.
2. **Feedback loop:** consume `TrainingSample` in a real DPO/RL trainer and feed learned corrections back into generation.
3. **Best-effort types:** promote high-value ones (timing, object, package) to full IR.
4. **Multi-instance:** Redis-backed cache + WS, Postgres, a task queue.
