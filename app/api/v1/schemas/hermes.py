from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from uuid import UUID


class HermesContextWindow(BaseModel):
    session_id: Optional[str] = None
    learning_path_id: Optional[int] = None
    current_topic: Optional[str] = None
    active_tasks: List[Dict[str, Any]] = Field(default_factory=list)
    recent_attempts: List[Dict[str, Any]] = Field(default_factory=list)
    scaffold_level: int = Field(default=1, ge=1, le=5)


class HermesAgentRequest(BaseModel):
    user_id: Optional[UUID | str] = None
    prompt: str = Field(default="", max_length=5000)
    mode: str = Field(default="ask")
    context_window: HermesContextWindow = Field(default_factory=HermesContextWindow)
    tools_enabled: List[str] = Field(
        default_factory=lambda: [
            "manage_tasks",
            "diagnose_gap",
            "generate_scaffold_hint",
            "update_learning_state",
            "generate_summary",
        ]
    )
    stream: bool = True


class HermesAgentSSEEvent(BaseModel):
    event: str = "token"
    data: Dict[str, Any] = Field(default_factory=dict)


class HermesNonStreamResponse(BaseModel):
    user_id: Optional[str] = None
    reply: str
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    scaffold_level: int = Field(default=1, ge=1, le=5)
    processing_time_ms: int
    mode_used: str
