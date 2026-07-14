from pydantic import BaseModel
from datetime import datetime
from typing import List, Dict, Any, Optional

class AuthResponse(BaseModel):
    user_id: str
    token: str

class SessionResponse(BaseModel):
    session_id: str
    created_at: datetime
    title: str

class MessageResponse(BaseModel):
    message_id: str
    status: str
    ws_url: str

class UpdateMessageResponse(BaseModel):
    message_id: str
    version: int
    status: str
    ws_url: str

class DiagramResponse(BaseModel):
    diagram_id: str
    diagram_type: str
    plantuml_code: str
    svg: str  # re-rendered on demand from plantuml_code (not persisted)
    ir: Dict[str, Any]
    is_valid: bool
    is_fallback: bool = False
    version: int

class FeedbackResponse(BaseModel):
    feedback_id: str
    status: str = "accepted"

class SessionListResponse(BaseModel):
    sessions: List[SessionResponse]

class MessageListResponse(BaseModel):
    class MessageItem(BaseModel):
        message_id: str
        prompt: str
        diagram_types: List[str]
        version: int
        status: str = "complete"
        created_at: datetime
    messages: List[MessageItem]
