from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.db import get_db, User, Diagram, Message
from app.core.dependencies import get_current_user
from app.schemas.requests import FeedbackRequest
from app.schemas.responses import FeedbackResponse
from app.services.feedback_service import store_feedback

router = APIRouter(prefix="/feedback", tags=["Feedback"])


@router.post("", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    request: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if request.diagram_id:
        result = await db.execute(select(Diagram).where(Diagram.id == request.diagram_id))
        if not result.scalars().first():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Diagram not found")
    else:
        result = await db.execute(select(Message).where(Message.id == request.message_id))
        if not result.scalars().first():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")

    feedback_id = await store_feedback(request, current_user.id, db)
    return FeedbackResponse(feedback_id=feedback_id, status="accepted")
