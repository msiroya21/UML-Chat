# UML Chatbot — Technical Specification

> **Version:** 0.3.0-draft  
> **Date:** 2026-07-11  
> **Status:** Awaiting Review  
> **Scope:** Interview round — core API servers, ~60 minutes  

---

## 1. Problem Statement

Build a **chat-based platform** that accepts a natural-language software design prompt and generates syntactically valid UML diagrams. The platform must handle three scenarios:

| Scenario | Description |
|---|---|
| **New User** | Submit prompt + diagram types → receive generated UML diagrams |
| **Iterative Update** | Existing user sends updated prompt → LLM receives both previous and new prompt → produces fresh IR |
| **Feedback Loop** | User provides feedback → stored asynchronously and routed to LangChain ART plugin for RL-based improvement |

### 1.1 Minimum Input Contract

```json
{
  "prompt": "<natural-language software design description>",
  "diagram_types": ["sequence", "component", "class", "activity"]
}
```

### 1.2 Supported UML 2.x Diagram Types

**Structure (7):** Class, Object, Component, Composite Structure, Deployment, Package, Profile  
**Behavior (7):** Use Case, Activity, State Machine, Sequence, Communication, Interaction Overview, Timing

---

## 2. Architecture

```
                    React Chat UI (Vite)
                            │
                            │ HTTPS + WebSocket
                            ▼
                     API Server (FastAPI)
                            │
             ┌──────────────┴───────────────┐
             │                              │
      Authentication                 Session Manager
      (JWT, simple)                  (in-memory / SQLite)
             │                              │
             └──────────────┬───────────────┘
                            ▼
                  Conversation Service
                            │
            Stores chat history + prompt versions
            Detects if request is NEW or UPDATE
                            │
                            ▼
               ┌────────────────────────────┐
               │   Generation Orchestrator  │
               │                            │
               │   Owns the full generation │
               │   lifecycle. Steps:        │
               │                            │
               │   1. Prompt Processing     │
               │   2. Diagram Selection     │
               │   3. Parallel IR Gen       │
               │   4. Validate + Repair     │
               │   5. Code Gen (IR→PlantUML)│
               │   6. Render (PlantUML→SVG) │
               │   7. Stream progress via WS│
               └────────────┬───────────────┘
                            │
                            ▼
                   Prompt Processor
                            │
                • Normalize & sanitize input
                • For UPDATES: bundle previous
                  prompt + new prompt together
                  (no IR diffing — full regen)
                            │
                            ▼
               ┌────────────────────────────┐
               │     Diagram Selector       │
               │                            │
               │  User may pass explicit    │
               │  diagram_types[], or the   │
               │  LLM auto-selects the most │
               │  relevant types from the   │
               │  prompt context.           │
               └────────────┬───────────────┘
                            │
          Selected types, e.g. [sequence, component, class]
                            │
         ┌──────────────────┼──────────────────┐
         ▼                  ▼                  ▼
   ┌──────────┐      ┌──────────┐       ┌──────────┐
   │ Sequence │      │Component │       │  Class   │
   │ IR Gen   │      │ IR Gen   │       │  IR Gen  │
   │ (LLM)    │      │ (LLM)    │       │  (LLM)   │
   └────┬─────┘      └────┬─────┘       └────┬─────┘
        │                  │                  │
        └──────────────────┼──────────────────┘
                           │
                    IR (Structured JSON)
                           │
                           ▼
                  ┌─────────────────┐
                  │  IR Validator   │
                  │  (Pydantic +    │
                  │   semantic)     │
                  └───┬─────────┬───┘
                   pass       fail
                    │           │
                    │           ▼
                    │    Auto-Repair Agent
                    │    (re-prompt LLM with
                    │     schema + errors,
                    │     up to 3 retries)
                    │           │
                    ▼           ▼
                  ┌─────────────────┐
                  │  Code Generator │
                  │  IR → PlantUML  │
                  │  (deterministic)│
                  └────────┬────────┘
                           │
                    PlantUML DSL string
                           │
                           ▼
                  ┌─────────────────┐
                  │  DSL Validator  │
                  │  plantuml       │
                  │  -syntax check  │
                  └───┬─────────┬───┘
                   pass       fail → re-prompt (up to 3x)
                    │
                    ▼
                  ┌─────────────────┐
                  │  PlantUML       │
                  │  Renderer       │
                  │  (JAR → SVG)    │
                  └────────┬────────┘
                           │
                           ▼
                    SVG sent to Frontend

               Feedback Service (fire-and-forget)
                       │
                       ▼
            LangChain ART Plugin (async)
                       │
                       ▼
               Feedback DB (SQLite)
```

### 2.1 Orchestrator Process (Step by Step)

This is the core pipeline. Every generation request — new or update — flows through these exact steps:

```
Step 1: PROMPT PROCESSING
        ┌─────────────────────────────────────────┐
        │ NEW request:                            │
        │   prompt_context = user_prompt          │
        │                                         │
        │ UPDATE request:                         │
        │   prompt_context = previous_prompt      │
        │                   + "\n---\n"           │
        │                   + new_prompt          │
        │                                         │
        │ (No IR diffing. LLM gets full context   │
        │  and generates fresh IR every time.)    │
        └─────────────────────┬───────────────────┘
                              │
                              ▼
Step 2: DIAGRAM SELECTION
        ┌─────────────────────────────────────────┐
        │ If user provided diagram_types[]:       │
        │   selected = user's list                │
        │                                         │
        │ If diagram_types is empty/omitted:      │
        │   LLM analyzes the prompt and returns   │
        │   a list of recommended diagram types   │
        │   (lightweight classification call)     │
        └─────────────────────┬───────────────────┘
                              │
                              ▼
Step 3: PARALLEL IR GENERATION
        ┌─────────────────────────────────────────┐
        │ For each selected diagram type:         │
        │   asyncio.gather(                       │
        │     generate_ir("sequence", prompt),     │
        │     generate_ir("component", prompt),    │
        │     generate_ir("class", prompt),        │
        │   )                                     │
        │                                         │
        │ Each call hits the LLM with:            │
        │   - System prompt (diagram-type specific)│
        │   - IR JSON schema for that type        │
        │   - Few-shot example of valid IR        │
        │   - User's prompt_context               │
        │                                         │
        │ LLM returns structured JSON IR.         │
        │ (No streaming of partial JSON —         │
        │  wait for complete response.)           │
        └─────────────────────┬───────────────────┘
                              │
                              ▼
Step 4: VALIDATE + REPAIR
        ┌─────────────────────────────────────────┐
        │ For each IR:                            │
        │   1. Pydantic schema validation         │
        │   2. Semantic checks (entities > 0,     │
        │      no orphans, valid refs)            │
        │   3. If invalid → re-prompt LLM with    │
        │      original prompt + IR + errors      │
        │   4. Max 3 retries per diagram          │
        └─────────────────────┬───────────────────┘
                              │
                              ▼
Step 5: CODE GENERATION (IR → PlantUML)
        ┌─────────────────────────────────────────┐
        │ Deterministic, no LLM involved.         │
        │                                         │
        │ sequence_ir_to_plantuml(ir) → string    │
        │ class_ir_to_plantuml(ir) → string       │
        │ component_ir_to_plantuml(ir) → string   │
        │ ...                                     │
        │                                         │
        │ Pure functions, unit-testable.           │
        └─────────────────────┬───────────────────┘
                              │
                              ▼
Step 6: RENDER (PlantUML → SVG)
        ┌─────────────────────────────────────────┐
        │ java -jar plantuml.jar -tsvg -pipe      │
        │                                         │
        │ Input: PlantUML DSL string              │
        │ Output: SVG string                      │
        │                                         │
        │ If render fails (syntax error in DSL):  │
        │   → Auto-repair: re-prompt LLM to fix   │
        │     the IR, then re-run steps 5+6       │
        │   → Max 3 retries                       │
        │   → If all fail: return raw DSL string  │
        │     for manual inspection               │
        └─────────────────────┬───────────────────┘
                              │
                              ▼
Step 7: STREAM RESULTS
        ┌─────────────────────────────────────────┐
        │ WebSocket pushes:                       │
        │   - Progress frames at each stage       │
        │   - Final diagram_result per type       │
        │     (SVG + PlantUML code + IR)          │
        │   - Completion frame                    │
        │                                         │
        │ Each diagram streams independently.     │
        │ Fast diagrams arrive first.             │
        └─────────────────────────────────────────┘
```

### 2.2 Why a Generation Orchestrator?

| Problem | How Orchestrator Solves It |
|---|---|
| LLM outputs invalid IR | Runs validate → repair → re-validate loop (up to 3x) |
| User requests 4 diagram types | Dispatches parallel LLM calls, streams results as each completes |
| Updated prompt arrives | Bundles previous + new prompt, sends to LLM for fresh IR generation |
| LLM returns prose instead of JSON | Detects via structural check, re-prompts with stricter constraints |
| Partial failures (2/4 diagrams succeed) | Returns successful diagrams immediately, retries failures independently |

### 2.3 Intermediate Representation (IR)

The LLM does **not** generate PlantUML directly. It produces a **structured JSON IR**. A deterministic code generator then converts IR → PlantUML DSL.

**Why IR before PlantUML?**

| Benefit | Explanation |
|---|---|
| **Syntax isolation** | LLM never writes raw PlantUML, so it can't produce PlantUML syntax errors. The code generator is deterministic and tested. |
| **Validation at semantic level** | We can check entity counts, relationship completeness, and orphan nodes on structured JSON — much easier than parsing PlantUML text. |
| **Feedback precision** | Corrections map to IR fields (e.g., "missing entity X"), making training data cleaner for ART. |
| **Testability** | IR → PlantUML code generators are pure functions with zero LLM dependency. Unit-testable with fixed inputs. |

**IR Schemas:**

```json
// Sequence Diagram IR
{
  "diagram_type": "sequence",
  "title": "SEBI Circular Parsing Flow",
  "participants": [
    { "id": "user", "label": "Compliance Officer", "type": "actor" },
    { "id": "scraper", "label": "SEBI Scraper Service", "type": "component" },
    { "id": "parser", "label": "Circular Parser", "type": "component" },
    { "id": "db", "label": "Compliance DB", "type": "database" }
  ],
  "messages": [
    { "from": "user", "to": "scraper", "label": "Trigger circular fetch", "type": "sync", "order": 1 },
    { "from": "scraper", "to": "parser", "label": "Raw circular PDF", "type": "async", "order": 2 },
    { "from": "parser", "to": "db", "label": "Store parsed clauses", "type": "sync", "order": 3 },
    { "from": "db", "to": "user", "label": "Gap analysis results", "type": "return", "order": 4 }
  ],
  "fragments": [
    {
      "type": "alt",
      "label": "API available",
      "covers": ["scraper", "parser"],
      "messages": [2, 3],
      "else": { "label": "API unavailable", "messages": [] }
    }
  ]
}
```

```json
// Class Diagram IR
{
  "diagram_type": "class",
  "title": "Compliance Domain Model",
  "classes": [
    {
      "id": "circular",
      "name": "SEBICircular",
      "attributes": [
        { "name": "circular_id", "type": "str", "visibility": "public" },
        { "name": "publish_date", "type": "date", "visibility": "public" },
        { "name": "raw_text", "type": "str", "visibility": "private" }
      ],
      "methods": [
        { "name": "parse_clauses", "return_type": "List[Clause]", "visibility": "public" }
      ]
    },
    {
      "id": "clause",
      "name": "Clause",
      "attributes": [
        { "name": "clause_number", "type": "str", "visibility": "public" },
        { "name": "text", "type": "str", "visibility": "public" },
        { "name": "compliance_type", "type": "ComplianceType", "visibility": "public" }
      ],
      "methods": []
    }
  ],
  "relationships": [
    {
      "from": "circular",
      "to": "clause",
      "type": "composition",
      "label": "contains",
      "multiplicity": { "from": "1", "to": "1..*" }
    }
  ]
}
```

```json
// Component Diagram IR
{
  "diagram_type": "component",
  "title": "Compliance Monitoring System",
  "components": [
    { "id": "scraper", "name": "SEBI Scraper", "stereotype": "service" },
    { "id": "parser", "name": "Circular Parser", "stereotype": "service" },
    { "id": "gap_engine", "name": "Gap Analysis Engine", "stereotype": "service" },
    { "id": "db", "name": "Compliance DB", "stereotype": "database" }
  ],
  "interfaces": [
    { "id": "i_fetch", "name": "ICircularFetch", "provided_by": "scraper", "required_by": ["parser"] },
    { "id": "i_store", "name": "IClauseStore", "provided_by": "db", "required_by": ["parser", "gap_engine"] }
  ],
  "dependencies": [
    { "from": "gap_engine", "to": "parser", "label": "parsed clauses" }
  ]
}
```

---

## 3. Tech Stack

| Layer | Technology | Rationale |
|---|---|---|
| **Frontend** | React (Vite) | Component model, fast dev server |
| **UML Rendering** | PlantUML JAR (server-side → SVG) | Single engine, covers all 14 UML 2.x types, no client-side complexity |
| **Backend** | FastAPI (Python 3.12+) | Async-native, Pydantic validation, LangChain ecosystem |
| **LLM Framework** | LangChain | ART plugin, prompt templating, structured output |
| **LLM Provider** | OpenAI GPT-4o / Gemini 2.5 Pro (env-configurable) | Best code generation quality |
| **Database** | SQLite (via SQLAlchemy) | Zero-config, single file, sufficient for interview |
| **Cache** | In-memory dict | Prompt-response caching, no external deps |
| **WebSocket** | FastAPI WebSocket native | Streaming progress to frontend |
| **Auth** | Simple JWT (PyJWT) | Minimal, stateless |

---

## 4. API Contracts

### 4.1 Auth

#### `POST /api/v1/auth/register`
```json
// Request
{ "email": "user@example.com", "password": "pass", "name": "Jane" }
// Response 201
{ "user_id": "uuid", "token": "jwt" }
```

#### `POST /api/v1/auth/login`
```json
// Request
{ "email": "user@example.com", "password": "pass" }
// Response 200
{ "user_id": "uuid", "token": "jwt" }
```

---

### 4.2 Sessions & Messages

#### `POST /api/v1/sessions`
```json
// Request (Header: Authorization: Bearer <jwt>)
{ "title": "Compliance System" }
// Response 201
{ "session_id": "uuid", "created_at": "ISO-8601" }
```

#### `POST /api/v1/sessions/{session_id}/messages`

New prompt submission. Returns immediately; results stream via WebSocket.

```json
// Request
{
  "prompt": "I am working on a compliance monitoring solution...",
  "diagram_types": ["sequence", "component", "class"]
}

// Response 202
{
  "message_id": "uuid",
  "status": "processing",
  "ws_url": "/ws/stream/{message_id}"
}
```

#### `PUT /api/v1/sessions/{session_id}/messages/{message_id}`

Update an existing prompt. Orchestrator bundles previous prompt + new prompt and sends to LLM for fresh IR generation (no IR diffing).

```json
// Request
{
  "prompt": "<updated prompt>",
  "diagram_types": ["sequence", "component", "class", "deployment"]
}

// Response 202
{
  "message_id": "uuid",
  "version": 2,
  "status": "processing",
  "ws_url": "/ws/stream/{message_id}?v=2"
}
```

#### `GET /api/v1/sessions/{session_id}/messages`
```json
// Response 200
{
  "messages": [
    {
      "message_id": "uuid",
      "role": "user",
      "prompt": "...",
      "diagram_types": ["sequence"],
      "version": 1,
      "created_at": "ISO-8601"
    }
  ]
}
```

---

### 4.3 WebSocket Streaming

#### `ws://host/ws/stream/{message_id}`

The orchestrator pushes **progress frames only** — no partial JSON streaming. Diagram results arrive as complete payloads when each diagram finishes.

```jsonc
// Progress updates (per diagram, at each pipeline stage)
{ "type": "progress", "diagram_type": "sequence", "stage": "selecting_diagrams", "percent": 10 }
{ "type": "progress", "diagram_type": "sequence", "stage": "generating_ir", "percent": 40 }
{ "type": "progress", "diagram_type": "sequence", "stage": "validating_ir", "percent": 60 }
{ "type": "progress", "diagram_type": "sequence", "stage": "generating_plantuml", "percent": 75 }
{ "type": "progress", "diagram_type": "sequence", "stage": "rendering_svg", "percent": 90 }

// Diagram result (complete payload — sent when a diagram finishes, not blocked by others)
{
  "type": "diagram_result",
  "diagram_type": "sequence",
  "plantuml_code": "@startuml\nparticipant User\n...\n@enduml",
  "svg": "<svg>...</svg>",
  "ir": { ... },
  "validation": { "is_valid": true, "errors": [], "warnings": [] }
}

// Completion (all diagrams done)
{ "type": "complete", "diagrams_generated": 3, "total_time_ms": 8200 }

// Error (per diagram, non-fatal — other diagrams still arrive)
{
  "type": "error",
  "diagram_type": "deployment",
  "error_code": "GENERATION_FAILED",
  "message": "Failed after 3 repair attempts",
  "partial_code": "@startuml\n..."
}
```

---

### 4.4 Diagrams

#### `GET /api/v1/sessions/{session_id}/messages/{message_id}/diagrams`
```json
// Response 200
{
  "diagrams": [
    {
      "diagram_id": "uuid",
      "diagram_type": "sequence",
      "plantuml_code": "@startuml\n...\n@enduml",
      "svg": "<svg>...</svg>",
      "ir": { ... },
      "is_valid": true,
      "version": 1
    }
  ]
}
```

#### `GET /api/v1/sessions/{session_id}/messages/{message_id}/diagrams/{diagram_id}?format=svg|png`

Export endpoint. Returns rendered image.

---

### 4.5 Feedback

#### `POST /api/v1/feedback`

Fire-and-forget. No status polling endpoint — feedback processing is fully async.

```json
// Request
{
  "diagram_id": "uuid",
  "rating": 4,
  "feedback_type": "correction",
  "feedback_text": "Missing error handling for SEBI API timeout",
  "corrections": {
    "missing_elements": ["error_handler"],
    "incorrect_relationships": [
      { "from": "Parser", "to": "DB", "issue": "Should be async" }
    ]
  }
}

// Response 201
{ "feedback_id": "uuid", "status": "accepted" }
```

No `GET /feedback/{id}/status` endpoint. The user is not expected to poll for feedback processing status — it happens in the background and improves future generations transparently.

---

## 5. Data Models

```
User                Session              Message              Diagram             Feedback
-----               -------              -------              -------             --------
id (PK)             id (PK)              id (PK)              id (PK)             id (PK)
email               user_id (FK)         session_id (FK)      message_id (FK)     diagram_id (FK)
name                title                role                 diagram_type        user_id (FK)
password_hash       created_at           prompt               plantuml_code       rating (1-5)
created_at          updated_at           diagram_types[]      svg (text)          feedback_type
                                         version              ir (JSON)           feedback_text
                                         parent_msg_id        is_valid            corrections (JSON)
                                         created_at           version             created_at
                                                              created_at
```

**Key indexes:** `sessions(user_id)`, `messages(session_id, created_at)`, `diagrams(message_id)`, `feedback(diagram_id)`

---

## 6. Key Technical Considerations

### 6.1 UML Rendering on UI

**Single engine: PlantUML only.**

All rendering happens server-side. The frontend receives SVG strings and embeds them directly.

| Aspect | Approach |
|---|---|
| **Rendering engine** | PlantUML JAR running locally: `java -jar plantuml.jar -tsvg -pipe` |
| **Diagram coverage** | All 14 UML 2.x diagram types — no gaps, no fallbacks |
| **Frontend display** | SVG embedded via `dangerouslySetInnerHTML` (sanitized) or `<img src="data:image/svg+xml;base64,...">` |
| **Interactive features** | Zoom/pan via CSS transforms on the SVG container; code view toggle to show PlantUML DSL |
| **Export** | SVG (direct), PNG (via PlantUML `-tpng` flag) |

**Why PlantUML only (no Mermaid)?**
- Mermaid only covers ~6 of 14 UML types. PlantUML covers all 14.
- Single engine = simpler code generator (only one target DSL), simpler validation, simpler rendering pipeline.
- The latency trade-off (server-side render ~200-800ms vs client-side ~50-150ms) is acceptable since LLM generation itself takes 3-10 seconds anyway — PlantUML render time is noise.

---

### 6.2 Syntax Validation & Error Control

The IR layer eliminates most syntax errors. Validation is two-tiered:

```
LLM → IR (JSON) → Validate IR → Code Generator → Validate DSL → Render SVG
                       |                               |
                  IR validation                   DSL validation
                  (Pydantic schema,               (plantuml -syntax)
                   entity counts,                      |
                   orphan detection)              fail → Auto-Repair
                       |                          (re-prompt LLM to
                  fail → re-prompt LLM             fix IR, up to 3x)
                  with schema + errors
```

**Validation layers:**

| Layer | What | How |
|---|---|---|
| **1. IR Schema** | JSON structure matches Pydantic model per diagram type | `SequenceDiagramIR.model_validate(json)` — catches missing fields, wrong types |
| **2. IR Semantic** | Entity count > 0, no orphan nodes, all relationship refs point to valid entity IDs | Custom validators in orchestrator |
| **3. PlantUML Syntax** | Generated PlantUML parses without errors | `java -jar plantuml.jar -syntax` — returns exit code + error lines |
| **4. Auto-Repair** | Feed errors back to LLM to fix the IR | Re-prompt: original prompt + broken IR + error messages; max 3 retries |
| **5. Graceful Degradation** | If all retries fail, return raw PlantUML code + error details | Frontend shows code in a text area for manual inspection |

---

### 6.3 Latency Minimization

| Strategy | Impact | Implementation |
|---|---|---|
| **WebSocket progress streaming** | User sees activity immediately | Push stage updates as orchestrator progresses through pipeline |
| **Parallel diagram generation** | Total time ≈ slowest single diagram, not sum of all | `asyncio.gather()` — each diagram type is an independent coroutine |
| **Prompt-response caching** | Skip LLM for identical prompts | `cache[sha256(prompt + diagram_type)] = ir + plantuml + svg` |
| **No partial JSON streaming** | Avoids parsing overhead and half-built JSON errors | Wait for complete LLM response; stream progress frames instead |
| **PlantUML process pool** | Avoid JVM cold-start on every render | Keep PlantUML running as a subprocess; pipe stdin/stdout per request |

---

### 6.4 Feedback Collection & RL Training

Feedback is **fire-and-forget** from the user's perspective. No status polling.

```
User submits feedback
        │
        ▼
Feedback Service
  • Validate input (Pydantic)
  • Persist to SQLite (feedback table)
  • Return 201 immediately
        │
        ▼ (async background task)
Preprocessing Worker
  • Build (prompt, chosen_output, rejected_output) triplets
  • chosen = user-corrected IR or high-rated IR (rating >= 4)
  • rejected = original IR if rating < 3
        │
        ▼
LangChain ART Plugin
  • Prompt optimization (not full fine-tuning)
  • Updates few-shot examples in system prompt
  • Adjusts generation parameters per diagram type
```

**Training data format:**
```json
{
  "input": { "prompt": "...", "diagram_type": "sequence" },
  "chosen": { "ir": { ... }, "rating": 5 },
  "rejected": { "ir": { ... }, "rating": 2 },
  "corrections": { ... },
  "metadata": { "user_hash": "sha256", "model_version": "v1", "timestamp": "ISO-8601" }
}
```

For interview scope: feedback is collected and stored. ART integration is a stub that logs training samples and updates a prompt template file.

---

## 7. User Scenario Flows

### 7.1 Scenario 1: New User

```
User → POST /auth/register → JWT
User → POST /sessions → session_id
User → POST /sessions/{id}/messages { prompt, diagram_types: ["sequence","class"] }
     → 202 { message_id, ws_url }
User → Connect ws_url

Orchestrator:
  1. Process prompt (normalize, sanitize)
  2. Diagram selection: user specified ["sequence", "class"]
  3. Parallel: generate_ir("sequence", prompt) + generate_ir("class", prompt)
  4. Validate each IR (Pydantic + semantic)
  5. Code gen: ir_to_plantuml() for each
  6. Render: plantuml → SVG for each

User ← progress: { stage: "selecting_diagrams", percent: 10 }
     ← progress: { stage: "generating_ir", diagram_type: "sequence", percent: 40 }
     ← progress: { stage: "rendering_svg", diagram_type: "sequence", percent: 90 }
     ← diagram_result: { type: "sequence", svg: "...", plantuml_code: "...", ir: {...} }
     ← progress: { stage: "rendering_svg", diagram_type: "class", percent: 90 }
     ← diagram_result: { type: "class", svg: "...", plantuml_code: "...", ir: {...} }
     ← complete: { diagrams_generated: 2 }

User → Frontend embeds SVGs, shows PlantUML code toggle
```

### 7.2 Scenario 2: Existing User — Updated Prompt

```
User → PUT /sessions/{id}/messages/{msg_id} { updated_prompt, diagram_types }
     → 202 { message_id, version: 2, ws_url }

Orchestrator:
  1. Load previous prompt from message history
  2. Bundle:  prompt_context = previous_prompt + "\n---\n" + new_prompt
  3. Diagram selection (from updated diagram_types)
  4. Send prompt_context to LLM → fresh IR for each diagram type
     (NO IR diffing — full regeneration with context)
  5. Validate, code gen, render as normal

User ← progress + diagram_result frames as usual
     ← complete
```

### 7.3 Scenario 3: Existing User — Feedback

```
User → POST /feedback { diagram_id, rating: 3, feedback_text: "...", corrections: {...} }
     → 201 { feedback_id, status: "accepted" }

(That's it from the user's perspective. No polling. No status check.)

Background:
  1. Feedback stored in DB
  2. Async worker builds training triplets
  3. Passes to ART plugin stub
  4. Improves future generations transparently
```

---

## 8. Edge Cases & Error Handling

### 8.1 LLM Output Issues

| Edge Case | Handling |
|---|---|
| **LLM returns invalid JSON IR** | Pydantic validation catches it; re-prompt with schema + error; 3 retries |
| **IR is valid JSON but semantically empty** | Semantic check (entity count = 0); re-prompt: "generate a non-trivial diagram with at least 3 entities" |
| **LLM returns wrong diagram type** | IR `diagram_type` field doesn't match request; discard and re-prompt |
| **LLM returns prose instead of JSON** | Detect absence of JSON markers (`{`); re-prompt with "respond ONLY with valid JSON" |
| **Excessively large IR (>50 entities)** | Truncate and warn; suggest user split into sub-systems |
| **Code generator produces invalid PlantUML from valid IR** | Deterministic bug — log it, return IR + raw code for manual inspection |
| **PlantUML render fails on valid-looking DSL** | Capture stderr from PlantUML JAR; feed errors to repair agent; 3 retries |

### 8.2 Concurrency & State

| Edge Case | Handling |
|---|---|
| **New prompt while previous is generating** | Orchestrator cancels in-flight `asyncio` tasks; starts new generation; notifies client via WS |
| **Double-click submission** | Client sends idempotency key (UUID); server deduplicates |
| **WebSocket disconnect mid-stream** | Orchestrator persists results to DB; client reconnects and fetches via REST `GET /diagrams` |
| **Multi-tab same session** | Last-write-wins with version field; 409 on conflict |

### 8.3 Performance

| Edge Case | Handling |
|---|---|
| **Long prompt (>8K tokens)** | Summarize via LLM before generating IR; warn user |
| **LLM rate limit** | Exponential backoff; WS frame with estimated wait time |
| **PlantUML JAR timeout** | 15s timeout; return raw PlantUML DSL for inspection |

### 8.4 Security

| Edge Case | Handling |
|---|---|
| **Prompt injection** | System prompt isolation; user prompt is a separate `user` message, never interpolated into system prompt |
| **XSS via generated SVG** | Sanitize SVG (strip `<script>`, `on*` attributes); use `<img>` with data URI instead of innerHTML |
| **JWT expiry during generation** | Validate at request start only; streaming continues; next request needs fresh token |
| **Feedback spam** | Rate limit: 10 feedback per session per hour |

### 8.5 Data Consistency

| Edge Case | Handling |
|---|---|
| **Feedback on deleted diagram** | Soft deletes only; feedback remains linkable |
| **Model version changes between request and retry** | Pin model version per message; cache keys include version |
| **PlantUML JAR crashes** | Catch subprocess errors; return error frame via WS; don't crash the server |

---

## 9. Project Structure

```
UML_Chatbot/
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── ChatPanel.jsx          # Input + message list
│   │   │   ├── DiagramPanel.jsx       # SVG display + PlantUML code toggle
│   │   │   ├── FeedbackWidget.jsx     # Rating + correction form
│   │   │   └── SessionSidebar.jsx     # Session list
│   │   ├── hooks/
│   │   │   └── useWebSocket.js        # WS connection + progress handling
│   │   ├── services/
│   │   │   └── api.js                 # REST client
│   │   ├── App.jsx
│   │   └── main.jsx
│   ├── index.html
│   └── package.json
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── auth.py                # Register, login, JWT
│   │   │   ├── sessions.py            # CRUD sessions + messages
│   │   │   ├── diagrams.py            # Diagram retrieval + export
│   │   │   ├── feedback.py            # Feedback submission (fire-and-forget)
│   │   │   └── ws.py                  # WebSocket streaming endpoint
│   │   ├── core/
│   │   │   ├── config.py              # Env vars, model config
│   │   │   └── security.py            # JWT encode/decode
│   │   ├── models/
│   │   │   └── db.py                  # SQLAlchemy models
│   │   ├── services/
│   │   │   ├── orchestrator.py        # ** Generation Orchestrator (7 steps) **
│   │   │   ├── prompt_processor.py    # Normalize, sanitize, bundle prev+new
│   │   │   ├── diagram_selector.py    # User-specified or LLM-recommended types
│   │   │   ├── planner.py             # LLM call → IR generation
│   │   │   ├── code_generator.py      # IR → PlantUML DSL (deterministic)
│   │   │   ├── validator.py           # IR schema + PlantUML syntax validation
│   │   │   ├── repair_agent.py        # Auto-repair loop
│   │   │   ├── renderer.py            # PlantUML JAR wrapper → SVG
│   │   │   ├── cache.py               # In-memory prompt-response cache
│   │   │   └── feedback_service.py    # Store + ART stub
│   │   ├── schemas/
│   │   │   ├── requests.py            # Pydantic request models
│   │   │   ├── responses.py           # Pydantic response models
│   │   │   └── ir.py                  # ** IR Pydantic models per diagram type **
│   │   ├── prompts/
│   │   │   ├── system_prompt.txt
│   │   │   ├── ir_schema_sequence.json
│   │   │   ├── ir_schema_class.json
│   │   │   ├── ir_schema_component.json
│   │   │   └── few_shot_examples/
│   │   └── main.py
│   ├── tests/
│   │   ├── test_code_generator.py     # Unit tests: IR → PlantUML
│   │   ├── test_validator.py
│   │   └── test_orchestrator.py
│   └── requirements.txt
│
├── SPEC.md
└── README.md
```

---

## 10. Implementation Priority (60-min Scope)

| Priority | Component | Time Est. | Notes |
|---|---|---|---|
| **P0** | FastAPI skeleton + routes | 10 min | Auth, sessions, messages, feedback endpoints |
| **P0** | Generation Orchestrator (7 steps) | 15 min | Core loop: prompt → select → IR → validate → codegen → render → respond |
| **P0** | IR schemas (Pydantic) + code generator | 10 min | At least sequence + class + component |
| **P0** | Validator (IR + PlantUML syntax) | 5 min | Pydantic schema check + `plantuml -syntax` |
| **P1** | WebSocket progress streaming | 5 min | Progress-only frames from orchestrator |
| **P1** | React frontend (chat + SVG display) | 10 min | Minimal chat panel + SVG embed |
| **P2** | Feedback endpoint + ART stub | 5 min | Store feedback, log training sample |
| **P2** | Auto-repair agent | Stretch | LLM re-prompt loop on validation failure |

**Out of scope for interview:** OAuth, Kubernetes, API gateway, monitoring, full ART training pipeline, PNG/PDF export, Mermaid.js.
