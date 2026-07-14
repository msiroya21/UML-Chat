import asyncio
from fastapi import APIRouter, Depends, HTTPException, status, Response, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from app.models.db import get_db, User, Session, Message, Diagram
from app.core.dependencies import get_current_user
from app.schemas.responses import DiagramResponse
from app.core.config import get_settings
from app.services.renderer import render_plantuml_to_svg, encode_plantuml, get_client

settings = get_settings()

router = APIRouter(prefix="/sessions/{session_id}/messages/{message_id}/diagrams", tags=["Diagrams"])

@router.get("", response_model=List[DiagramResponse])
async def list_diagrams(
    session_id: str,
    message_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Verify session belongs to user
    session_result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == current_user.id)
    )
    if not session_result.scalars().first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
        
    # Verify message belongs to session
    message_result = await db.execute(
        select(Message).where(Message.id == message_id, Message.session_id == session_id)
    )
    if not message_result.scalars().first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
        
    result = await db.execute(
        select(Diagram).where(Diagram.message_id == message_id)
    )
    diagrams = result.scalars().all()

    # SVG is not persisted — re-render each from plantuml_code (parallel, no LLM).
    async def _render(code: str) -> str:
        try:
            svg, _ = await render_plantuml_to_svg(code)
            return svg
        except Exception:
            return ""

    svgs = await asyncio.gather(*[_render(d.plantuml_code) for d in diagrams])

    return [
        DiagramResponse(
            diagram_id=d.id,
            diagram_type=d.diagram_type,
            plantuml_code=d.plantuml_code,
            svg=svg,
            ir=d.ir,
            is_valid=d.is_valid,
            is_fallback=d.is_fallback,
            version=d.version,
        )
        for d, svg in zip(diagrams, svgs)
    ]

@router.get("/{diagram_id}")
async def get_diagram_file(
    session_id: str,
    message_id: str,
    diagram_id: str,
    format: str = Query("svg", regex="^(svg|png)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Verify session belongs to user
    session_result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == current_user.id)
    )
    if not session_result.scalars().first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
        
    # Verify diagram exists and matches message
    result = await db.execute(
        select(Diagram).where(Diagram.id == diagram_id, Diagram.message_id == message_id)
    )
    diagram = result.scalars().first()
    if not diagram:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Diagram not found")
        
    if format == "svg":
        try:
            svg, _ = await render_plantuml_to_svg(diagram.plantuml_code)
        except Exception:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to render SVG")
        return Response(content=svg, media_type="image/svg+xml")
    else:
        # Request PNG from the PlantUML server via the shared HTTP client.
        encoded = encode_plantuml(diagram.plantuml_code)
        url = f"{settings.PLANTUML_SERVER_URL.rstrip('/')}/png/{encoded}"
        try:
            response = await get_client().get(url)
            if response.status_code == 200:
                return Response(content=response.content, media_type="image/png")
        except Exception:
            pass

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to render PNG via PlantUML server"
        )
