import logging
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.db import Feedback, Diagram, Message, TrainingSample

logger = logging.getLogger(__name__)


async def store_feedback(request, user_id: str, db: AsyncSession) -> str:
    """
    Persist feedback (always anchored to a message — single join path) plus a durable,
    correctly-attributed training sample (real user_id + generation provenance).
    """
    diagram = None
    message_id = request.message_id
    if request.diagram_id:
        diagram = (await db.execute(
            select(Diagram).where(Diagram.id == request.diagram_id)
        )).scalars().first()
        if diagram and not message_id:
            message_id = diagram.message_id  # derive parent so the row always has message_id

    if not message_id:
        raise ValueError("Cannot resolve message_id for feedback")

    record = Feedback(
        message_id=message_id,
        diagram_id=request.diagram_id,
        user_id=user_id,
        rating=request.rating,
        feedback_type=request.feedback_type,
        feedback_text=request.feedback_text,
        corrections=request.corrections,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    message = (await db.execute(select(Message).where(Message.id == message_id))).scalars().first()
    promoted = _training_labels(request, diagram)
    sample = _build_training_sample(request, user_id, message, diagram, promoted)
    db.add(TrainingSample(
        feedback_id=record.id,
        user_id=user_id,
        scope="diagram" if diagram else "session",
        # Query-able columns (see db.TrainingSample) — the same values also live in `sample`.
        signal=promoted["signal"],
        diagram_type=promoted["diagram_type"],
        model=promoted["model"],
        prompt_version=promoted["prompt_version"],
        sample=sample,
    ))
    await db.commit()
    logger.info("Stored feedback %s (scope=%s) + training sample.", record.id, "diagram" if diagram else "session")
    return record.id


def _training_labels(request, diagram) -> dict:
    """The trainer-facing labels, computed once for both the columns and the JSON payload."""
    if diagram is None:
        return {"signal": None, "diagram_type": None, "model": None, "prompt_version": None}
    rating = request.rating
    signal = "chosen" if (rating or 0) >= 4 else "rejected" if (rating or 5) < 3 else "neutral"
    return {
        "signal": signal,
        "diagram_type": diagram.diagram_type,
        "model": diagram.model,
        "prompt_version": diagram.prompt_version,
    }


def _build_training_sample(request, user_id: str, message, diagram, promoted: dict) -> dict:
    """A training sample a trainer can actually use: real user, real generation provenance."""
    sample = {
        "user_id": user_id,
        "input": {
            "prompt": message.prompt if message else None,
            "diagram_types": message.diagram_types if message else None,
        },
        "feedback": {
            "type": request.feedback_type,
            "rating": request.rating,
            "text": request.feedback_text,
            "corrections": request.corrections,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if diagram is not None:
        sample["diagram"] = {
            "diagram_type": diagram.diagram_type,
            "ir": diagram.ir,
            "model": diagram.model,
            "prompt_version": diagram.prompt_version,
        }
        sample["signal"] = promoted["signal"]
    return sample
