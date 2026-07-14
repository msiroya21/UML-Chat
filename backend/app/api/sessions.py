from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc
from typing import List, Optional
from app.models.db import get_db, User, Session, Message, Diagram, SessionLocal
from app.core.dependencies import get_current_user
from app.schemas.requests import CreateSessionRequest, CreateMessageRequest, UpdateMessageRequest, RenameSessionRequest
from app.schemas.responses import (
    SessionResponse, SessionListResponse, MessageResponse,
    UpdateMessageResponse, MessageListResponse
)

router = APIRouter(prefix="/sessions", tags=["Sessions & Messages"])


async def _auto_title_bg(session_id: str, prompt: str):
    from app.services.title_generator import generate_session_title_async
    title = await generate_session_title_async(prompt)
    async with SessionLocal() as db:
        result = await db.execute(select(Session).where(Session.id == session_id))
        s = result.scalars().first()
        if s:
            s.title = title
            await db.commit()


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    request: CreateSessionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    title = request.title or "New Session"
    new_session = Session(
        user_id=current_user.id,
        title=title
    )
    db.add(new_session)
    await db.commit()
    await db.refresh(new_session)
    return SessionResponse(session_id=new_session.id, created_at=new_session.created_at, title=new_session.title)


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    offset = (page - 1) * per_page
    result = await db.execute(
        select(Session)
        .where(Session.user_id == current_user.id)
        .order_by(desc(Session.updated_at))
        .offset(offset)
        .limit(per_page)
    )
    sessions = result.scalars().all()
    return SessionListResponse(
        sessions=[
            SessionResponse(session_id=s.id, created_at=s.created_at, title=s.title)
            for s in sessions
        ]
    )


@router.patch("/{session_id}", response_model=SessionResponse)
async def rename_session(
    session_id: str,
    request: RenameSessionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == current_user.id)
    )
    session = result.scalars().first()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    session.title = request.title
    await db.commit()
    await db.refresh(session)
    return SessionResponse(session_id=session.id, created_at=session.created_at, title=session.title)


@router.get("/{session_id}/messages", response_model=MessageListResponse)
async def list_messages(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == current_user.id)
    )
    session = result.scalars().first()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at)
    )
    messages = result.scalars().all()

    return MessageListResponse(
        messages=[
            MessageListResponse.MessageItem(
                message_id=m.id,
                prompt=m.prompt,
                diagram_types=m.diagram_types,
                version=m.version,
                status=m.status,
                created_at=m.created_at
            )
            for m in messages
        ]
    )


@router.post("/{session_id}/messages", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_message(
    session_id: str,
    request: CreateMessageRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == current_user.id)
    )
    session = result.scalars().first()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    allowed_types = {
        "sequence", "class", "component", "activity", "usecase", "state", "object",
        "deployment", "package", "composite_structure", "communication",
        "interaction_overview", "timing", "profile"
    }
    for dt in request.diagram_types:
        if dt not in allowed_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid diagram type: '{dt}'. Must be one of {allowed_types}"
            )

    new_message = Message(
        session_id=session_id,
        prompt=request.prompt,
        diagram_types=request.diagram_types or [],
        version=1,
        status="processing",
    )
    db.add(new_message)
    await db.commit()
    await db.refresh(new_message)

    from app.services.orchestrator import run_orchestrator_background
    background_tasks.add_task(
        run_orchestrator_background,
        message_id=new_message.id,
        prompt_context=request.prompt,
        diagram_types=new_message.diagram_types,
    )

    # Only auto-title when the user hasn't named the session (don't clobber a chosen title).
    if session.title == "New Session":
        background_tasks.add_task(_auto_title_bg, session_id, request.prompt)

    ws_url = f"/ws/stream/{new_message.id}"
    return MessageResponse(
        message_id=new_message.id,
        status="processing",
        ws_url=ws_url
    )


@router.put("/{session_id}/messages/{message_id}", response_model=UpdateMessageResponse, status_code=status.HTTP_202_ACCEPTED)
async def update_message(
    session_id: str,
    message_id: str,
    request: UpdateMessageRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == current_user.id)
    )
    session = result.scalars().first()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    result = await db.execute(
        select(Message).where(Message.id == message_id, Message.session_id == session_id)
    )
    old_message = result.scalars().first()
    if not old_message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")

    allowed_types = {
        "sequence", "class", "component", "activity", "usecase", "state", "object",
        "deployment", "package", "composite_structure", "communication",
        "interaction_overview", "timing", "profile"
    }
    for dt in request.diagram_types:
        if dt not in allowed_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid diagram type: '{dt}'. Must be one of {allowed_types}"
            )

    updated_message = Message(
        session_id=session_id,
        prompt=request.prompt,
        diagram_types=request.diagram_types,
        version=old_message.version + 1,
        parent_msg_id=old_message.id,
        status="processing",
    )
    db.add(updated_message)
    await db.commit()
    await db.refresh(updated_message)

    # Full-history context: walk the parent_msg_id lineage oldest -> newest.
    all_msgs = (await db.execute(
        select(Message).where(Message.session_id == session_id)
    )).scalars().all()
    by_id = {m.id: m for m in all_msgs}
    chain: list[str] = []
    node = updated_message
    while node is not None:
        chain.append(node.prompt)
        node = by_id.get(node.parent_msg_id) if node.parent_msg_id else None
    chain.reverse()

    # Snapshot the previous turn's diagrams so unchanged ones can be carried forward
    # and targeted ones regenerated from their prior IR (no-stub-overwrite on failure).
    prev_diagrams = (await db.execute(
        select(Diagram).where(Diagram.message_id == old_message.id)
    )).scalars().all()
    prev_snapshots = {
        d.diagram_type: {
            "plantuml_code": d.plantuml_code, "ir": d.ir,
            "is_valid": d.is_valid, "is_fallback": d.is_fallback,
            "model": d.model, "prompt_version": d.prompt_version,
        }
        for d in prev_diagrams
    }

    from app.services.orchestrator import run_update_background
    background_tasks.add_task(
        run_update_background,
        message_id=updated_message.id,
        prompt_chain=chain,
        requested_types=request.diagram_types,
        prev_snapshots=prev_snapshots,
    )

    ws_url = f"/ws/stream/{updated_message.id}"
    return UpdateMessageResponse(
        message_id=updated_message.id,
        version=updated_message.version,
        status="processing",
        ws_url=ws_url,
    )
