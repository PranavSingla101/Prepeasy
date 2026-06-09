import time
from dataclasses import dataclass, field

from backend.schemas.questions import QuestionBank
from backend.schemas.session import TranscriptEntry


@dataclass
class InterviewState:
    session_id: str
    question_bank: QuestionBank
    current_question_idx: int = 0
    follow_up_count: int = 0
    key_facts_mentioned: list = field(default_factory=list)
    transcript_log: list = field(default_factory=list)
    silence_streak: int = 0
    session_active: bool = True

    @property
    def current_question(self):
        return self.question_bank.questions[self.current_question_idx]

    @property
    def current_question_id(self) -> str:
        return self.current_question.id
