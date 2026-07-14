from pydantic import BaseModel, Field, model_validator
from typing import List, Optional, Dict, Any
from app.core.config import get_settings

_MAX_PROMPT = get_settings().MAX_PROMPT_CHARS

class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str

class LoginRequest(BaseModel):
    email: str
    password: str

class CreateSessionRequest(BaseModel):
    title: Optional[str] = None

class RenameSessionRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)

class CreateMessageRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=_MAX_PROMPT)
    diagram_types: Optional[List[str]] = Field(default_factory=list)

class UpdateMessageRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=_MAX_PROMPT)
    diagram_types: List[str]

class FeedbackRequest(BaseModel):
    diagram_id: Optional[str] = None
    message_id: Optional[str] = None
    rating: Optional[int] = Field(None, ge=1, le=5)
    feedback_type: str = Field(..., description="correction, praise, or suggestion")
    feedback_text: str
    corrections: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def require_at_least_one_id(self) -> "FeedbackRequest":
        if not self.diagram_id and not self.message_id:
            raise ValueError("Either diagram_id or message_id must be provided")
        return self
