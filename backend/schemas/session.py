import logging
from typing import Literal

from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)


class TranscriptEntry(BaseModel):
    speaker: Literal["user", "agent"]
    text: str
    question_id: str
    ts: float


class OrchestratorDecision(BaseModel):
    action: Literal["follow_up", "probe", "next_question", "close"]
    text: str

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("OrchestratorDecision.text must be non-empty — fix the LLM prompt")
        return v
