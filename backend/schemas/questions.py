from typing import Literal
from pydantic import BaseModel, model_validator

CATEGORY_COUNTS = {
    "behavioral": 10,
    "technical": 8,
    "gap_probing": 5,
    "situational": 3,
    "closing": 2,
}


class Question(BaseModel):
    id: str
    category: Literal["behavioral", "technical", "gap_probing", "situational", "closing"]
    text: str
    source_ref: str
    follow_up_vague: str
    follow_up_strong: str


class QuestionBank(BaseModel):
    session_id: str
    resume_name: str
    questions: list[Question]

    @model_validator(mode="after")
    def validate_bank(self) -> "QuestionBank":
        if len(self.questions) != 28:
            raise ValueError(
                f"QuestionBank must have exactly 28 questions, got {len(self.questions)}"
            )

        counts: dict[str, int] = {}
        for q in self.questions:
            counts[q.category] = counts.get(q.category, 0) + 1

        for category in CATEGORY_COUNTS:
            if category not in counts:
                raise ValueError(f"No questions found for category '{category}'")

        for q in self.questions:
            if q.category == "gap_probing" and not q.source_ref:
                raise ValueError(
                    f"gap_probing question '{q.id}' must have a non-empty source_ref"
                )

        return self
