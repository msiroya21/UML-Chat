import asyncio
import logging
import time
from typing import Optional
from sqlalchemy.future import select
from app.core.config import get_settings
from app.models.db import SessionLocal, Message, Diagram
from app.core.ws_manager import ws_manager
from app.services.diagram_selector import select_diagrams
from app.services.planner import generate_ir, GenerationError, PROMPT_VERSION
from app.services.llm_client import LLMConfigError
from app.services.validator import validate_ir, validate_plantuml
from app.services.repair_agent import repair_ir
from app.services.code_generator import ir_to_plantuml
from app.services.renderer import render_plantuml_to_svg
from app.services.cache import get_cached_diagram, set_cached_diagram
from app.schemas.ir import IR_SCHEMA_MAP
from app.services.update_planner import ACTION_GENERATE, ACTION_REGENERATE, ACTION_CARRY_FORWARD

logger = logging.getLogger(__name__)
settings = get_settings()

# Throttle concurrent LLM calls so a many-type request doesn't trip Groq rate limits.
_LLM_SEMAPHORE = asyncio.Semaphore(4)


# ─── DB helpers ─────────────────────────────────────────────────────────────
async def _upsert_diagram(message_id: str, diagram_type: str, *, plantuml_code: str, ir: dict,
                          is_valid: bool, is_fallback: bool, version: int,
                          model: Optional[str], prompt_version: Optional[str]) -> str:
    """Insert or update the (message_id, diagram_type) row — respects the unique constraint."""
    async with SessionLocal() as db:
        row = (await db.execute(
            select(Diagram).where(Diagram.message_id == message_id, Diagram.diagram_type == diagram_type)
        )).scalars().first()
        if row is None:
            row = Diagram(message_id=message_id, diagram_type=diagram_type)
            db.add(row)
        row.plantuml_code = plantuml_code
        row.ir = ir
        row.is_valid = is_valid
        row.is_fallback = is_fallback
        row.version = version
        row.model = model
        row.prompt_version = prompt_version
        await db.commit()
        await db.refresh(row)
        return row.id


async def _set_message_status(message_id: str, status: str) -> None:
    async with SessionLocal() as db:
        m = (await db.execute(select(Message).where(Message.id == message_id))).scalars().first()
        if m:
            m.status = status
            await db.commit()


# ─── WS helpers ─────────────────────────────────────────────────────────────
async def _progress(message_id: str, diagram_type: str, stage: str, percent: int) -> None:
    await ws_manager.broadcast_to_message(message_id, {
        "type": "progress", "diagram_type": diagram_type, "stage": stage, "percent": percent,
    })


async def _result(message_id: str, diagram_id: str, diagram_type: str, plantuml_code: str, svg: str,
                  ir: dict, *, is_valid: bool, is_fallback: bool, error: Optional[str] = None) -> None:
    await ws_manager.broadcast_to_message(message_id, {
        "type": "diagram_result",
        "diagram_id": diagram_id,
        "diagram_type": diagram_type,
        "plantuml_code": plantuml_code,
        "svg": svg,
        "ir": ir,
        "is_fallback": is_fallback,
        "validation": {"is_valid": is_valid, "errors": [error] if error else [], "warnings": []},
    })


# User-facing error text per code. The raw technical `detail` stays in the logs only,
# so the UI never shows a stack-y string or an internal exception message.
def _friendly_error(code: str, diagram_type: str) -> str:
    label = diagram_type.replace("_", " ")
    return {
        "CONFIG_ERROR": "The diagram service isn't configured correctly (check the API key).",
        "GENERATION_FAILED": (
            f"Couldn't generate a valid {label} diagram from this description. "
            "Try rephrasing or adding more detail."
        ),
        "INTERNAL_ERROR": f"Something went wrong generating the {label} diagram. Please try again.",
    }.get(code, f"Couldn't generate the {label} diagram.")


async def _error(message_id: str, diagram_type: str, code: str, detail: str, partial: Optional[str] = None) -> None:
    """Broadcast a friendly message to the UI; keep the technical `detail` in the logs."""
    logger.warning("Diagram '%s' error [%s]: %s", diagram_type, code, detail)
    await ws_manager.broadcast_to_message(message_id, {
        "type": "error", "diagram_type": diagram_type, "error_code": code,
        "message": _friendly_error(code, diagram_type), "partial_code": partial,
    })


async def _safe_render(plantuml_code: str) -> tuple[str, Optional[str]]:
    """Render, swallowing transport errors into an empty SVG (used on display-only paths)."""
    try:
        return await render_plantuml_to_svg(plantuml_code)
    except Exception as e:
        logger.warning("Render failed: %s", e)
        return "", str(e)


# ─── Carry-forward (no LLM) ─────────────────────────────────────────────────
async def _carry_forward(message_id: str, version: int, spec: dict) -> dict:
    diagram_type = spec["diagram_type"]
    prior = spec["prior"]
    svg, render_err = await _safe_render(prior["plantuml_code"])
    diagram_id = await _upsert_diagram(
        message_id, diagram_type,
        plantuml_code=prior["plantuml_code"], ir=prior["ir"],
        is_valid=(render_err is None) and not prior.get("is_fallback", False),
        is_fallback=prior.get("is_fallback", False),
        version=version, model=prior.get("model"), prompt_version=prior.get("prompt_version"),
    )
    await _result(message_id, diagram_id, diagram_type, prior["plantuml_code"], svg, prior["ir"],
                  is_valid=render_err is None, is_fallback=prior.get("is_fallback", False))
    logger.info("Carried forward '%s' unchanged for message %s.", diagram_type, message_id)
    return {"status": "success", "diagram_type": diagram_type}


# ─── Failure handling: show the REAL attempted code, never an example ───────
async def _handle_failure(message_id: str, version: int, spec: dict, err: GenerationError) -> dict:
    diagram_type = spec["diagram_type"]

    # no-stub-overwrite: a failed REGENERATION keeps the prior good diagram.
    if spec.get("action") == ACTION_REGENERATE and spec.get("prior"):
        logger.warning("Regen of '%s' failed (%s); carrying forward prior good diagram.", diagram_type, err)
        return await _carry_forward(message_id, version, spec)

    partial = err.partial_code
    if partial:
        # Persist + show the model's real attempt as code, flagged invalid — not a fake example.
        svg, _ = await _safe_render(partial) if partial.strip().startswith("@startuml") else ("", None)
        diagram_id = await _upsert_diagram(
            message_id, diagram_type, plantuml_code=partial,
            ir={"diagram_type": diagram_type, "_error": str(err)},
            is_valid=False, is_fallback=True, version=version,
            model=settings.LLM_MODEL, prompt_version=PROMPT_VERSION,
        )
        await _result(message_id, diagram_id, diagram_type, partial, svg,
                      {"diagram_type": diagram_type, "_error": str(err)},
                      is_valid=False, is_fallback=True, error=str(err))
        return {"status": "shown_invalid", "diagram_type": diagram_type}

    await _error(message_id, diagram_type, "GENERATION_FAILED", str(err))
    return {"status": "failed", "diagram_type": diagram_type}


# ─── Generate / regenerate pipeline ─────────────────────────────────────────
async def _generate_pipeline(message_id: str, prompt_context: str, version: int, spec: dict) -> dict:
    diagram_type = spec["diagram_type"]
    is_regen = spec["action"] == ACTION_REGENERATE
    prior_ir = spec.get("prior_ir") if is_regen else None
    loop = asyncio.get_running_loop()

    # Cache only fresh generations (edits must not reuse a stale render).
    if spec["action"] == ACTION_GENERATE:
        cached = get_cached_diagram(prompt_context, diagram_type)
        if cached:
            svg, render_err = await _safe_render(cached["plantuml_code"])
            diagram_id = await _upsert_diagram(
                message_id, diagram_type, plantuml_code=cached["plantuml_code"], ir=cached["ir"],
                is_valid=render_err is None, is_fallback=False, version=version,
                model=settings.LLM_MODEL, prompt_version=PROMPT_VERSION,
            )
            await _result(message_id, diagram_id, diagram_type, cached["plantuml_code"], svg,
                          cached["ir"], is_valid=render_err is None, is_fallback=False)
            return {"status": "success", "diagram_type": diagram_type}

    await _progress(message_id, diagram_type, "generating_ir", 40)
    try:
        ir_dict = await loop.run_in_executor(None, generate_ir, diagram_type, prompt_context, prior_ir)
    except LLMConfigError as e:
        await _error(message_id, diagram_type, "CONFIG_ERROR", f"LLM configuration error: {e}")
        return {"status": "failed", "diagram_type": diagram_type}
    except GenerationError as ge:
        return await _handle_failure(message_id, version, spec, ge)

    # Validate + repair. ONE repair budget is shared across the IR, DSL, and render
    # stages, decremented on every repair call — so total repairs never exceed
    # MAX_REPAIR_RETRIES no matter which stage consumes them.
    await _progress(message_id, diagram_type, "validating_ir", 60)
    repairs_left = settings.MAX_REPAIR_RETRIES

    def _attempt_no() -> int:
        return settings.MAX_REPAIR_RETRIES - repairs_left + 1

    is_valid, errors = validate_ir(diagram_type, ir_dict)
    while not is_valid and repairs_left > 0:
        ir_dict = await loop.run_in_executor(None, repair_ir, diagram_type, prompt_context, ir_dict, errors, _attempt_no())
        repairs_left -= 1
        is_valid, errors = validate_ir(diagram_type, ir_dict)
    if not is_valid:
        return await _handle_failure(message_id, version, spec,
                                     GenerationError(f"IR invalid after repair: {errors}"))

    await _progress(message_id, diagram_type, "generating_plantuml", 75)
    plantuml_code = ir_to_plantuml(diagram_type, ir_dict)
    dsl_valid, dsl_errors = validate_plantuml(plantuml_code)
    if not dsl_valid and diagram_type in IR_SCHEMA_MAP and repairs_left > 0:
        ir_dict = await loop.run_in_executor(
            None, repair_ir, diagram_type, prompt_context, ir_dict,
            [f"Generated PlantUML DSL error: {e}" for e in dsl_errors], _attempt_no())
        repairs_left -= 1
        if validate_ir(diagram_type, ir_dict)[0]:
            plantuml_code = ir_to_plantuml(diagram_type, ir_dict)
            dsl_valid, dsl_errors = validate_plantuml(plantuml_code)
    if not dsl_valid:
        return await _handle_failure(message_id, version, spec,
                                     GenerationError(f"PlantUML DSL invalid: {dsl_errors}", partial_code=plantuml_code))

    # Render + REAL syntax verification (PlantUML error image = failure).
    await _progress(message_id, diagram_type, "rendering_svg", 90)
    try:
        svg, render_err = await render_plantuml_to_svg(plantuml_code)
    except Exception as e:
        return await _handle_failure(message_id, version, spec,
                                     GenerationError(f"Render failed: {e}", partial_code=plantuml_code))

    if render_err and diagram_type in IR_SCHEMA_MAP and repairs_left > 0:
        ir_dict = await loop.run_in_executor(
            None, repair_ir, diagram_type, prompt_context, ir_dict,
            [f"Rendered diagram had a syntax error: {render_err}"], _attempt_no())
        repairs_left -= 1
        if validate_ir(diagram_type, ir_dict)[0]:
            plantuml_code = ir_to_plantuml(diagram_type, ir_dict)
            svg, render_err = await _safe_render(plantuml_code)
    if render_err:
        return await _handle_failure(message_id, version, spec,
                                     GenerationError(f"Failed syntax verification: {render_err}", partial_code=plantuml_code))

    # Success — cache (source of truth only) and persist.
    set_cached_diagram(prompt_context, diagram_type, {"ir": ir_dict, "plantuml_code": plantuml_code})
    diagram_id = await _upsert_diagram(
        message_id, diagram_type, plantuml_code=plantuml_code, ir=ir_dict,
        is_valid=True, is_fallback=False, version=version,
        model=settings.LLM_MODEL, prompt_version=PROMPT_VERSION,
    )
    await _result(message_id, diagram_id, diagram_type, plantuml_code, svg, ir_dict,
                  is_valid=True, is_fallback=False)
    return {"status": "success", "diagram_type": diagram_type}


async def process_single_diagram(message_id: str, prompt_context: str, version: int, spec: dict) -> dict:
    """Concurrency-throttled dispatch; guarantees exactly one terminal frame per type."""
    async with _LLM_SEMAPHORE:
        try:
            if spec["action"] == ACTION_CARRY_FORWARD:
                return await _carry_forward(message_id, version, spec)
            return await _generate_pipeline(message_id, prompt_context, version, spec)
        except Exception as e:
            logger.exception("Unexpected failure generating '%s'.", spec.get("diagram_type"))
            await _error(message_id, spec.get("diagram_type", "unknown"), "INTERNAL_ERROR", f"Unexpected error: {e}")
            return {"status": "failed", "diagram_type": spec.get("diagram_type")}


async def run_orchestrator_background(
    message_id: str,
    prompt_context: str,
    diagram_types: Optional[list[str]] = None,
    action_plan: Optional[list[dict]] = None,
) -> None:
    """
    Entry point for background generation.
    - Create path: pass `diagram_types` (or empty for auto-select); all specs are 'generate'.
    - Update path: pass a prebuilt `action_plan` of specs (generate/regenerate/carry_forward).
    """
    start = time.time()
    try:
        async with SessionLocal() as db:
            message = (await db.execute(select(Message).where(Message.id == message_id))).scalars().first()
            if not message:
                logger.error("Message %s not found; aborting orchestration.", message_id)
                return
            version = message.version

        await _progress(message_id, "all", "selecting_diagrams", 10)

        if action_plan is None:
            loop = asyncio.get_running_loop()
            try:
                selected = await loop.run_in_executor(None, select_diagrams, prompt_context, diagram_types)
                selected = list(dict.fromkeys(selected))
            except Exception as e:
                logger.error("Diagram selection failed: %s", e)
                selected = ["sequence", "class"]
            specs = [{"diagram_type": t, "action": ACTION_GENERATE} for t in selected]
        else:
            specs = action_plan

        if not specs:
            await _set_message_status(message_id, "complete")
            await ws_manager.broadcast_to_message(message_id, {
                "type": "complete", "diagrams_generated": 0,
                "total_time_ms": int((time.time() - start) * 1000),
            })
            return

        results = await asyncio.gather(
            *[process_single_diagram(message_id, prompt_context, version, s) for s in specs],
            return_exceptions=True,
        )
        generated = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "success")

        await _set_message_status(message_id, "complete")
        await ws_manager.broadcast_to_message(message_id, {
            "type": "complete", "diagrams_generated": generated,
            "total_time_ms": int((time.time() - start) * 1000),
        })
        logger.info("Orchestration done for %s: %d/%d succeeded.", message_id, generated, len(specs))

    except Exception as e:
        logger.exception("Orchestration crashed for %s: %s", message_id, e)
        await _set_message_status(message_id, "failed")
        await ws_manager.broadcast_to_message(message_id, {
            "type": "complete", "diagrams_generated": 0,
            "total_time_ms": int((time.time() - start) * 1000),
        })


async def run_update_background(
    message_id: str,
    prompt_chain: list[str],
    requested_types: list[str],
    prev_snapshots: dict[str, dict],
) -> None:
    """
    Background entry for an UPDATE: classify which existing diagrams the instruction
    targets, build the generate/regenerate/carry_forward plan, then run generation.
    (Classification is an LLM call — done here in the background, not in the request handler.)
    """
    from app.services.update_planner import classify_update_targets, compute_update_actions
    from app.services.prompt_processor import build_context

    context = build_context(prompt_chain)
    update_text = prompt_chain[-1] if prompt_chain else ""

    # Empty selection on an update means "keep the same diagram set as before": carry all
    # forward and let the intent classifier pick which to regenerate. (New types still need
    # their chip; auto-select isn't reused here as it would drop carried-forward types.)
    if not requested_types:
        requested_types = list(prev_snapshots.keys())

    prev_good = {t for t, s in prev_snapshots.items() if s.get("is_valid") and not s.get("is_fallback")}

    loop = asyncio.get_running_loop()
    try:
        targeted = await loop.run_in_executor(None, classify_update_targets, update_text, list(prev_good))
    except Exception as e:
        logger.warning("Update classification failed (%s); carrying existing diagrams forward.", e)
        targeted = []

    actions = compute_update_actions(requested_types, prev_good, set(targeted))
    specs: list[dict] = []
    for dtype, action in actions.items():
        spec = {"diagram_type": dtype, "action": action}
        snap = prev_snapshots.get(dtype)
        if snap and action in (ACTION_REGENERATE, ACTION_CARRY_FORWARD):
            spec["prior"] = {
                "plantuml_code": snap["plantuml_code"], "ir": snap["ir"],
                "is_fallback": snap.get("is_fallback", False),
                "model": snap.get("model"), "prompt_version": snap.get("prompt_version"),
            }
            if action == ACTION_REGENERATE:
                spec["prior_ir"] = snap["ir"]
        specs.append(spec)

    logger.info("Update plan for %s: %s", message_id, {s["diagram_type"]: s["action"] for s in specs})
    await run_orchestrator_background(message_id, context, action_plan=specs)
