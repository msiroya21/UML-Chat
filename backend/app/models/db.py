import uuid
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import (
    String, ForeignKey, DateTime, Integer, JSON, Boolean,
    UniqueConstraint, Index, event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import get_settings

settings = get_settings()


def _utcnow() -> datetime:
    """Timezone-aware UTC timestamp (naive datetime.utcnow is deprecated)."""
    return datetime.now(timezone.utc)


# Async SQLAlchemy engine
engine = create_async_engine(settings.DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


# Enforce foreign keys + concurrency-friendly settings on every SQLite connection.
# (SQLite ignores FK constraints unless PRAGMA foreign_keys=ON; WAL + busy_timeout
# let the orchestrator's parallel per-diagram writes coexist without "database is locked".)
if settings.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    sessions: Mapped[List["Session"]] = relationship(
        "Session", back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    user: Mapped["User"] = relationship("User", back_populates="sessions")
    messages: Mapped[List["Message"]] = relationship(
        "Message", back_populates="session", cascade="all, delete-orphan", passive_deletes=True
    )

    # Matches list_sessions ordering (user's sessions, newest-updated first).
    __table_args__ = (Index("ix_sessions_user_updated", "user_id", "updated_at"),)


class Message(Base):
    """
    One user turn (an initial request or an update). The assistant's output is the
    set of Diagram rows attached to this turn — there is no assistant Message, so
    there is no `role` column. Lineage across versions is the parent_msg_id chain;
    created_at is used only for display ordering.
    """
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    prompt: Mapped[str] = mapped_column(String, nullable=False)
    # Requested metadata only — the diagram types actually produced are the Diagram rows.
    diagram_types: Mapped[List[str]] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    parent_msg_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    # processing | complete | failed — so a crashed generation is not an invisible orphan.
    status: Mapped[str] = mapped_column(String, nullable=False, default="processing")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    session: Mapped["Session"] = relationship("Session", back_populates="messages")
    diagrams: Mapped[List["Diagram"]] = relationship(
        "Diagram", back_populates="message", cascade="all, delete-orphan", passive_deletes=True
    )
    feedbacks: Mapped[List["Feedback"]] = relationship(
        "Feedback", back_populates="message", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (Index("ix_messages_session_created", "session_id", "created_at"),)


class Diagram(Base):
    """
    A generated diagram for one turn. Source of truth is `ir` + `plantuml_code`;
    the rendered SVG is NOT stored — it is re-rendered from plantuml_code on demand
    (live over WS during generation, and on session re-open).
    """
    __tablename__ = "diagrams"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    message_id: Mapped[str] = mapped_column(
        String, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    diagram_type: Mapped[str] = mapped_column(String, nullable=False)
    plantuml_code: Mapped[str] = mapped_column(String, nullable=False)
    ir: Mapped[dict] = mapped_column(JSON, nullable=False)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # Provenance — so a feedback/training sample can be tied to what produced the row.
    model: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    message: Mapped["Message"] = relationship("Message", back_populates="diagrams")
    feedbacks: Mapped[List["Feedback"]] = relationship(
        "Feedback", back_populates="diagram", passive_deletes=True
    )

    # One diagram per type per turn — kills duplicate rows on re-run; enables upsert.
    __table_args__ = (UniqueConstraint("message_id", "diagram_type", name="uq_diagram_message_type"),)


class Feedback(Base):
    """
    Feedback always hangs off a message (single join path). `diagram_id` is an
    optional refinement identifying which diagram within the turn — NOT a second parent.
    """
    __tablename__ = "feedbacks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    message_id: Mapped[str] = mapped_column(
        String, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    diagram_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("diagrams.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    feedback_type: Mapped[str] = mapped_column(String, nullable=False)
    feedback_text: Mapped[str] = mapped_column(String, nullable=False)
    corrections: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    message: Mapped["Message"] = relationship("Message", back_populates="feedbacks")
    diagram: Mapped[Optional["Diagram"]] = relationship("Diagram", back_populates="feedbacks")


class TrainingSample(Base):
    """
    Durable ART/RL training samples (replaces logging to stdout). Write-only for now;
    a trainer can consume these later. Tied to real user + generation provenance.
    """
    __tablename__ = "training_samples"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    feedback_id: Mapped[str] = mapped_column(
        String, ForeignKey("feedbacks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String, nullable=False)  # "diagram" | "session"
    # Trainer-facing labels promoted out of the JSON blob so a trainer can filter/index
    # directly (e.g. all "chosen" samples for "sequence") instead of scanning + parsing.
    # Null for session-scope feedback (no rated diagram). `sample` keeps the full payload.
    signal: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)  # chosen | rejected | neutral
    diagram_type: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    model: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    sample: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# Dependency for DB Session
async def get_db():
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

# Schema creation/evolution is owned entirely by Alembic (`alembic upgrade head`).
# The app deliberately does NOT create_all on startup, so there is one source of truth.
