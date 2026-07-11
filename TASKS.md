# UML Chatbot — Task Breakdown

> **Reference:** [SPEC.md](file:///c:/Users/HP/Desktop/UML_Chatbot/SPEC.md) (v0.3.0)  
> **Total Estimated Time:** ~60 minutes  
> **Legend:** `[ ]` todo · `[/]` in progress · `[x]` done  

---

## Requirements Summary

### Functional Requirements

| # | Requirement | Scenario |
|---|---|---|
| FR-1 | User can register and login, receiving a JWT token | All |
| FR-2 | User can create a chat session | All |
| FR-3 | User can submit a prompt + diagram types and receive generated UML diagrams | New User |
| FR-4 | If diagram_types is empty, the system auto-selects relevant types via LLM | New User |
| FR-5 | User can update an existing prompt; system bundles previous + new prompt and generates fresh IR | Iterative Update |
| FR-6 | User can submit feedback (rating, corrections) on a generated diagram; feedback is fire-and-forget | Feedback Loop |
| FR-7 | Feedback is stored and asynchronously routed to LangChain ART plugin stub | Feedback Loop |
| FR-8 | All diagrams are rendered as SVG via PlantUML (server-side only) | All |
| FR-9 | LLM produces structured JSON IR first; deterministic code generator converts IR → PlantUML | All |
| FR-10 | Invalid IR/DSL triggers auto-repair (re-prompt LLM with errors, up to 3 retries) | All |
| FR-11 | Progress is streamed to frontend via WebSocket (stage + percent, no partial JSON) | All |
| FR-12 | Each diagram type is generated in parallel; results arrive independently | All |
| FR-13 | User can retrieve previously generated diagrams via REST | All |

### Non-Functional Requirements

| # | Requirement |
|---|---|
| NFR-1 | Backend: FastAPI (Python 3.12+), async |
| NFR-2 | Frontend: React (Vite) |
| NFR-3 | Database: SQLite via SQLAlchemy |
| NFR-4 | Auth: Simple JWT (PyJWT), stateless |
| NFR-5 | Rendering: PlantUML JAR only (all 14 UML types) |
| NFR-6 | Caching: In-memory dict for prompt-response pairs |
| NFR-7 | LLM: OpenAI / Gemini, env-configurable |
| NFR-8 | No external infra dependencies (no Redis, Kong, K8s, Grafana) |

### Dependencies to Install

| Package | Purpose |
|---|---|
| `fastapi`, `uvicorn[standard]` | API server + WebSocket |
| `sqlalchemy`, `aiosqlite` | Database ORM + async SQLite |
| `pyjwt`, `passlib[bcrypt]` | JWT auth + password hashing |
| `langchain`, `langchain-openai` / `langchain-google-genai` | LLM orchestration |
| `pydantic` | Request/response + IR schema validation |
| `httpx` | Async HTTP client (if needed) |
| `python-multipart` | Form data parsing for FastAPI |
| PlantUML JAR (`plantuml.jar`) | Server-side UML rendering |
| Java runtime (JRE/JDK) | Required to run PlantUML |
| `react`, `vite` | Frontend scaffold |

---

## Task Breakdown

---

### Phase 1: Project Setup (~5 min)

- [x] **1.1 Initialize backend project**
  - [x] Create `backend/` directory structure matching spec §9
  - [x] Create `requirements.txt` with all Python dependencies
  - [x] Run `pip install -r requirements.txt`

- [x] **1.2 Initialize frontend project**
  - [x] Scaffold React app with Vite inside `frontend/`
  - [x] Verify `npm run dev` starts the dev server

- [x] **1.3 PlantUML setup**
  - [x] Download `plantuml.jar` into project root or `backend/`
  - [x] Verify Java is available: `java -version`
  - [x] Verify PlantUML works: `echo "@startuml\nBob -> Alice : hello\n@enduml" | java -jar plantuml.jar -tsvg -pipe`

- [x] **1.4 Environment config**
  - [x] Create `backend/app/core/config.py`
  - [x] Define settings: `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`, `PLANTUML_JAR_PATH`, `JWT_SECRET`, `DATABASE_URL`
  - [x] Load from environment variables with sensible defaults

---

### Phase 2: Database Models & Schemas (~5 min)

- [x] **2.1 SQLAlchemy models** — `backend/app/models/db.py`
  - [x] `User` table: id (UUID PK), email (unique), name, password_hash, created_at
  - [x] `Session` table: id (UUID PK), user_id (FK → User), title, created_at, updated_at
  - [x] `Message` table: id (UUID PK), session_id (FK → Session), role (user/assistant), prompt, diagram_types (JSON), version, parent_msg_id (nullable FK → self), created_at
  - [x] `Diagram` table: id (UUID PK), message_id (FK → Message), diagram_type, plantuml_code, svg, ir (JSON), is_valid, version, created_at
  - [x] `Feedback` table: id (UUID PK), diagram_id (FK → Diagram), user_id (FK → User), rating (1-5), feedback_type, feedback_text, corrections (JSON), created_at
  - [x] Database init function: create engine, create all tables on startup

- [x] **2.2 Pydantic request/response schemas** — `backend/app/schemas/requests.py` & `responses.py`
  - [x] `RegisterRequest`: email, password, name
  - [x] `LoginRequest`: email, password
  - [x] `AuthResponse`: user_id, token
  - [x] `CreateSessionRequest`: title (optional)
  - [x] `SessionResponse`: session_id, created_at, title
  - [x] `CreateMessageRequest`: prompt, diagram_types (list[str], optional)
  - [x] `MessageResponse`: message_id, status, ws_url
  - [x] `UpdateMessageRequest`: prompt, diagram_types
  - [x] `UpdateMessageResponse`: message_id, version, status, ws_url
  - [x] `DiagramResponse`: diagram_id, diagram_type, plantuml_code, svg, ir, is_valid, version
  - [x] `FeedbackRequest`: diagram_id, rating, feedback_type, feedback_text, corrections (optional)
  - [x] `FeedbackResponse`: feedback_id, status ("accepted")

- [x] **2.3 IR Pydantic schemas** — `backend/app/schemas/ir.py`
  - [x] `SequenceDiagramIR`: diagram_type, title, participants (list of {id, label, type}), messages (list of {from, to, label, type, order}), fragments (optional)
  - [x] `ClassDiagramIR`: diagram_type, title, classes (list of {id, name, attributes[], methods[]}), relationships (list of {from, to, type, label, multiplicity})
  - [x] `ComponentDiagramIR`: diagram_type, title, components (list of {id, name, stereotype}), interfaces (list of {id, name, provided_by, required_by[]}), dependencies (list of {from, to, label})
  - [x] Add validators: entity count > 0, no orphan references, diagram_type matches expected value
  - [x] `IR_SCHEMA_MAP`: dict mapping `"sequence" → SequenceDiagramIR`, `"class" → ClassDiagramIR`, etc.

---

### Phase 3: Auth & Security (~5 min)

- [x] **3.1 JWT utilities** — `backend/app/core/security.py`
  - [x] `hash_password(plain) → str` using passlib bcrypt
  - [x] `verify_password(plain, hashed) → bool`
  - [x] `create_jwt(user_id) → str` with expiry (e.g., 24h)
  - [x] `decode_jwt(token) → user_id` or raise 401

- [x] **3.2 Auth dependency** — reusable FastAPI dependency
  - [x] `get_current_user(token: str = Header) → User` — extracts Bearer token, decodes JWT, fetches user from DB
  - [x] Returns 401 if token is missing, expired, or invalid

- [x] **3.3 Auth routes** — `backend/app/api/auth.py`
  - [x] `POST /api/v1/auth/register` — validate input, check email uniqueness, hash password, create user, return JWT
  - [x] `POST /api/v1/auth/login` — validate input, verify password, return JWT

---

### Phase 4: Session & Message Routes (~5 min)

- [x] **4.1 Session routes** — `backend/app/api/sessions.py`
  - [x] `POST /api/v1/sessions` — create session, return session_id (requires auth)
  - [x] `GET /api/v1/sessions` — list user's sessions with pagination
  - [x] `GET /api/v1/sessions/{session_id}/messages` — list messages in a session

- [x] **4.2 Message submission route**
  - [x] `POST /api/v1/sessions/{session_id}/messages` — persist message to DB, kick off orchestrator as background task, return 202 with message_id + ws_url
  - [x] Validate session belongs to current user
  - [x] Validate diagram_types are from allowed set (or allow empty for auto-selection)

- [x] **4.3 Message update route**
  - [x] `PUT /api/v1/sessions/{session_id}/messages/{message_id}` — load previous prompt from DB, persist updated message (increment version), kick off orchestrator with previous+new prompt, return 202

- [x] **4.4 Diagram retrieval routes** — `backend/app/api/diagrams.py`
  - [x] `GET /api/v1/sessions/{session_id}/messages/{message_id}/diagrams` — return all diagrams for a message
  - [x] `GET /api/v1/sessions/{session_id}/messages/{message_id}/diagrams/{diagram_id}?format=svg|png` — return rendered image

---

### Phase 5: Generation Orchestrator (~15 min)

This is the core of the system. Each substep maps to the 7-step pipeline from SPEC §2.1.

- [x] **5.1 Prompt Processor** — `backend/app/services/prompt_processor.py`
  - [x] `process_prompt(new_prompt, previous_prompt=None) → str`
  - [x] If `previous_prompt` is None (NEW): return `new_prompt` (normalized, stripped)
  - [x] If `previous_prompt` exists (UPDATE): return `previous_prompt + "\n---\nUpdated requirements:\n" + new_prompt`
  - [x] Basic sanitization: strip excessive whitespace, limit to 10K chars

- [x] **5.2 Diagram Selector** — `backend/app/services/diagram_selector.py`
  - [x] `select_diagrams(prompt, user_types=None) → list[str]`
  - [x] If `user_types` is provided and non-empty: validate against allowed list, return as-is
  - [x] If `user_types` is empty/None: call LLM with a lightweight classification prompt → return list of recommended diagram types
  - [x] Allowed types: `["sequence", "class", "component", "activity", "usecase", "state", "object", "deployment", "package", "composite_structure", "communication", "interaction_overview", "timing", "profile"]`

- [x] **5.3 Planner (IR Generator)** — `backend/app/services/planner.py`
  - [x] `generate_ir(diagram_type, prompt_context) → dict`
  - [x] Build LLM prompt: system prompt (diagram-type specific) + IR JSON schema + few-shot example + user's prompt_context
  - [x] Call LLM with `response_format=json` (structured output)
  - [x] Parse response as JSON
  - [x] Return raw dict (validation happens in next step)

- [x] **5.4 Validator** — `backend/app/services/validator.py`
  - [x] `validate_ir(diagram_type, ir_dict) → (is_valid, errors[])`
  - [x] Look up Pydantic model from `IR_SCHEMA_MAP[diagram_type]`
  - [x] Run `model.model_validate(ir_dict)` — catches structural errors
  - [x] Run semantic checks: entity count > 0, all relationship refs point to valid IDs, no orphan nodes
  - [x] Return (True, []) or (False, [list of error strings])
  - [x] `validate_plantuml(plantuml_code) → (is_valid, errors[])`
  - [x] Run `java -jar plantuml.jar -syntax` with the code piped to stdin
  - [x] Parse exit code + stderr for errors
  - [x] Return (True, []) or (False, [error lines])

- [x] **5.5 Code Generator** — `backend/app/services/code_generator.py`
  - [x] `ir_to_plantuml(diagram_type, ir_dict) → str`
  - [x] Dispatch to type-specific function: `sequence_ir_to_plantuml(ir)`, `class_ir_to_plantuml(ir)`, `component_ir_to_plantuml(ir)`
  - [x] Each function is a deterministic pure function: walks the IR JSON and emits valid PlantUML syntax
  - [x] `sequence_ir_to_plantuml(ir)`:
    - [x] Emit `@startuml` + title
    - [x] Emit `participant` declarations (with type: actor, component, database, etc.)
    - [x] Emit messages in order (sync: `->`, async: `->>`, return: `-->`)
    - [x] Emit fragments (alt/loop/opt blocks)
    - [x] Emit `@enduml`
  - [x] `class_ir_to_plantuml(ir)`:
    - [x] Emit `@startuml` + title
    - [x] Emit class declarations with attributes (visibility: `+`, `-`, `#`) and methods
    - [x] Emit relationships (composition: `*--`, aggregation: `o--`, inheritance: `--|>`, association: `--`)
    - [x] Emit multiplicity labels
    - [x] Emit `@enduml`
  - [x] `component_ir_to_plantuml(ir)`:
    - [x] Emit `@startuml` + title
    - [x] Emit component declarations with stereotypes
    - [x] Emit interface declarations (provided/required with lollipop notation)
    - [x] Emit dependencies
    - [x] Emit `@enduml`

- [x] **5.6 Repair Agent** — `backend/app/services/repair_agent.py`
  - [x] `repair_ir(diagram_type, prompt_context, broken_ir, errors, attempt) → dict`
  - [x] Build LLM prompt: "The following IR for a {diagram_type} diagram has errors: {errors}. Original prompt: {prompt_context}. Broken IR: {broken_ir}. Please fix it and return valid JSON."
  - [x] Call LLM, return new IR dict
  - [x] Called by orchestrator in a retry loop (max 3 attempts)

- [x] **5.7 Renderer** — `backend/app/services/renderer.py`
  - [x] `render_plantuml_to_svg(plantuml_code) → str`
  - [x] Run `java -jar plantuml.jar -tsvg -pipe` as subprocess
  - [x] Pipe `plantuml_code` to stdin, read SVG from stdout
  - [x] Handle timeout (15s), capture stderr
  - [x] Return SVG string or raise RenderError

- [x] **5.8 Cache** — `backend/app/services/cache.py`
  - [x] In-memory dict: `cache = {}`
  - [x] Key: `sha256(prompt_context + diagram_type)`
  - [x] Value: `{ ir, plantuml_code, svg }`
  - [x] `get(prompt, diagram_type) → cached result or None`
  - [x] `set(prompt, diagram_type, result) → None`

- [x] **5.9 Orchestrator** — `backend/app/services/orchestrator.py`
  - [x] `async generate_diagrams(message_id, prompt_context, diagram_types, ws_callback) → list[DiagramResult]`
  - [x] **Step 1:** Call prompt processor → `processed_prompt`
  - [x] **Step 2:** Call diagram selector → `selected_types`; send WS: `{ stage: "selecting_diagrams", percent: 10 }`
  - [x] **Step 3:** For each selected type, dispatch parallel coroutines via `asyncio.gather()`:
    - [x] Check cache first → if hit, return cached result immediately
    - [x] Send WS: `{ stage: "generating_ir", diagram_type, percent: 40 }`
    - [x] Call `generate_ir(type, processed_prompt)` → raw IR dict
    - [x] **Step 4:** Send WS: `{ stage: "validating_ir", percent: 60 }`
    - [x] Call `validate_ir(type, ir_dict)` → if invalid, call `repair_ir()` up to 3x
    - [x] If all retries fail → send WS error frame, skip this diagram
    - [x] **Step 5:** Send WS: `{ stage: "generating_plantuml", percent: 75 }`
    - [x] Call `ir_to_plantuml(type, ir_dict)` → PlantUML code
    - [x] Call `validate_plantuml(code)` → if invalid, repair and retry
    - [x] **Step 6:** Send WS: `{ stage: "rendering_svg", percent: 90 }`
    - [x] Call `render_plantuml_to_svg(code)` → SVG string
    - [x] Cache the result
    - [x] Send WS: `diagram_result` frame
  - [x] **Step 7:** After all coroutines complete → send WS: `{ type: "complete", diagrams_generated: N }`
  - [x] Persist all diagram results to DB

---

### Phase 6: WebSocket Endpoint (~5 min)

- [ ] **6.1 WebSocket route** — `backend/app/api/ws.py`
  - [ ] `ws://host/ws/stream/{message_id}` — accept WebSocket connection
  - [ ] Register the connection so the orchestrator can push frames to it
  - [ ] Handle client disconnect gracefully (orchestrator continues, results persist to DB)

- [ ] **6.2 WS message types** — define frame schemas
  - [ ] Progress frame: `{ type: "progress", diagram_type, stage, percent }`
  - [ ] Diagram result frame: `{ type: "diagram_result", diagram_type, plantuml_code, svg, ir, validation }`
  - [ ] Completion frame: `{ type: "complete", diagrams_generated, total_time_ms }`
  - [ ] Error frame: `{ type: "error", diagram_type, error_code, message, partial_code }`

- [ ] **6.3 Connect orchestrator to WS**
  - [ ] Orchestrator accepts a `ws_callback(frame_dict)` function
  - [ ] Each pipeline stage calls `ws_callback` with the appropriate frame
  - [ ] If no WebSocket connected (e.g., client disconnected), callback is a no-op

---

### Phase 7: Feedback Endpoint (~3 min)

- [ ] **7.1 Feedback route** — `backend/app/api/feedback.py`
  - [ ] `POST /api/v1/feedback` — validate input, persist to Feedback table, return 201 `{ feedback_id, status: "accepted" }`
  - [ ] No status polling endpoint. Fire-and-forget.

- [ ] **7.2 Feedback service** — `backend/app/services/feedback_service.py`
  - [ ] `store_feedback(request) → feedback_id` — write to DB
  - [ ] `build_training_sample(feedback) → dict` — convert feedback + original diagram into ART training triplet format:
    ```
    { input: { prompt, diagram_type },
      chosen: { ir, rating },
      rejected: { ir, rating },
      corrections, metadata }
    ```
  - [ ] ART stub: log the training sample to a file / stdout. No actual training.

---

### Phase 8: LLM Prompts (~5 min)

- [ ] **8.1 System prompt** — `backend/app/prompts/system_prompt.txt`
  - [ ] Role definition: "You are a UML diagram architect..."
  - [ ] Output format instructions: "Respond ONLY with valid JSON matching the provided schema"
  - [ ] Diagram-type-specific instructions appended dynamically

- [ ] **8.2 IR schema prompts** — one per diagram type
  - [ ] `ir_schema_sequence.json` — the Pydantic schema exported as JSON schema
  - [ ] `ir_schema_class.json`
  - [ ] `ir_schema_component.json`
  - [ ] These are injected into the LLM prompt so the model knows the exact output format

- [ ] **8.3 Few-shot examples** — `backend/app/prompts/few_shot_examples/`
  - [ ] `sequence_example.json` — one valid Sequence IR example
  - [ ] `class_example.json` — one valid Class IR example
  - [ ] `component_example.json` — one valid Component IR example
  - [ ] Each example includes the input prompt snippet + the expected IR output

- [ ] **8.4 Diagram selection prompt**
  - [ ] A lightweight prompt for the diagram selector: "Given the following software description, which UML diagram types would be most useful? Return a JSON array of type names."

---

### Phase 9: FastAPI App Assembly (~3 min)

- [ ] **9.1 Main app** — `backend/app/main.py`
  - [ ] Create FastAPI app instance
  - [ ] Include all routers: auth, sessions, diagrams, feedback, ws
  - [ ] Add CORS middleware (allow frontend origin)
  - [ ] Add startup event: initialize DB (create tables)
  - [ ] Add exception handlers for common errors (401, 404, 422)

- [ ] **9.2 Verify backend runs**
  - [ ] `uvicorn app.main:app --reload`
  - [ ] Hit `/docs` to verify Swagger UI shows all routes
  - [ ] Test `POST /auth/register` + `POST /auth/login` manually

---

### Phase 10: Frontend (~10 min)

- [ ] **10.1 API client** — `frontend/src/services/api.js`
  - [ ] Axios/fetch wrapper with base URL and JWT header injection
  - [ ] Functions: `register()`, `login()`, `createSession()`, `submitMessage()`, `updateMessage()`, `getDiagrams()`, `submitFeedback()`

- [ ] **10.2 WebSocket hook** — `frontend/src/hooks/useWebSocket.js`
  - [ ] Connect to `ws_url` returned from message submission
  - [ ] Handle frame types: progress, diagram_result, complete, error
  - [ ] Expose state: `{ isConnected, progress, diagrams, errors }`

- [ ] **10.3 Chat panel** — `frontend/src/components/ChatPanel.jsx`
  - [ ] Text input for prompt
  - [ ] Multi-select or text input for diagram_types
  - [ ] Submit button → calls `submitMessage()` → connects WS
  - [ ] Display message history

- [ ] **10.4 Diagram panel** — `frontend/src/components/DiagramPanel.jsx`
  - [ ] Display SVG diagrams received via WebSocket
  - [ ] Show progress indicator per diagram (stage + percent bar)
  - [ ] PlantUML code toggle (show/hide raw DSL)
  - [ ] Zoom/pan on SVG container

- [ ] **10.5 Feedback widget** — `frontend/src/components/FeedbackWidget.jsx`
  - [ ] Star rating (1-5)
  - [ ] Feedback text area
  - [ ] Feedback type selector (correction / praise / suggestion)
  - [ ] Submit → calls `submitFeedback()` → show "Thanks!" confirmation

- [ ] **10.6 Session sidebar** — `frontend/src/components/SessionSidebar.jsx`
  - [ ] List of user's sessions
  - [ ] Click to load session messages + diagrams
  - [ ] "New Session" button

- [ ] **10.7 App shell** — `frontend/src/App.jsx`
  - [ ] Layout: sidebar (sessions) | main area (chat + diagrams)
  - [ ] Auth gate: show login/register if no token, app if authenticated
  - [ ] Store JWT in localStorage

---

### Phase 11: Integration & Smoke Test (~4 min)

- [ ] **11.1 End-to-end test: New user flow**
  - [ ] Register → create session → submit prompt with `["sequence", "class"]` → verify WS progress frames arrive → verify SVGs render in frontend

- [ ] **11.2 End-to-end test: Update flow**
  - [ ] Submit initial prompt → get diagrams → update prompt via PUT → verify new diagrams are generated (full regen, no diff)

- [ ] **11.3 End-to-end test: Feedback flow**
  - [ ] Submit feedback on a diagram → verify 201 response → verify feedback row in DB

- [ ] **11.4 Edge case: Invalid LLM output**
  - [ ] Force an invalid IR response (mock) → verify validator catches it → verify repair agent is called → verify retry loop up to 3x → verify graceful degradation if all fail

- [ ] **11.5 Edge case: PlantUML render failure**
  - [ ] Send malformed PlantUML to renderer → verify error is caught → verify error frame sent via WS

---

## Execution Order Summary

```
Phase 1: Project Setup                          [~5 min]
    |
    v
Phase 2: Database Models & Schemas              [~5 min]
    |
    v
Phase 3: Auth & Security                        [~5 min]
    |
    v
Phase 4: Session & Message Routes               [~5 min]
    |
    v
Phase 5: Generation Orchestrator (CORE)         [~15 min]
    |  5.1 Prompt Processor
    |  5.2 Diagram Selector
    |  5.3 Planner (IR Generator)
    |  5.4 Validator
    |  5.5 Code Generator (IR → PlantUML)
    |  5.6 Repair Agent
    |  5.7 Renderer (PlantUML → SVG)
    |  5.8 Cache
    |  5.9 Orchestrator (wires 5.1–5.8 together)
    |
    v
Phase 6: WebSocket Endpoint                     [~5 min]
    |
    v
Phase 7: Feedback Endpoint                      [~3 min]
    |
    v
Phase 8: LLM Prompts                            [~5 min]
    |
    v
Phase 9: FastAPI App Assembly                    [~3 min]
    |
    v
Phase 10: Frontend                               [~10 min]
    |
    v
Phase 11: Integration & Smoke Test              [~4 min]
                                          ──────────────
                                          Total: ~65 min
```

> [!TIP]
> **If running short on time**, skip Phase 10 (Frontend) and Phase 11 (Integration tests). The backend is the core deliverable for the interview. The frontend can be a Swagger UI demo via FastAPI's built-in `/docs`.

> [!IMPORTANT]
> **Critical path:** Phases 2 → 5 → 6 are the backbone. If the orchestrator pipeline works end-to-end (prompt → IR → PlantUML → SVG → WS), the system is demonstrable even without a frontend.
