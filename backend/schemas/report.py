from typing import Optional

from pydantic import BaseModel, ValidationInfo, field_validator, model_validator


def _normalise_score(value: float) -> float:
    rounded = round(float(value), 1)
    if not (1 <= rounded <= 10):
        raise ValueError(f"Score must be between 1 and 10, got {rounded}")
    return rounded


def _is_grounded(value: str, allowed_quotes: set[str], *, exact: bool = False) -> bool:
    value_lower = value.strip().lower()
    for quote in allowed_quotes:
        quote_lower = quote.strip().lower()
        if exact and value_lower == quote_lower:
            return True
        if not exact and quote_lower and (value_lower in quote_lower or quote_lower in value_lower):
            return True
    return False


class DimensionBreakdown(BaseModel):
    relevance: float
    specificity: float
    structure: float
    communication: float

    @field_validator("relevance", "specificity", "structure", "communication")
    @classmethod
    def validate_average(cls, v: float) -> float:
        return _normalise_score(v)


class CategoryScore(BaseModel):
    category: str
    average_score: float
    answered_count: int
    skipped_count: int

    @field_validator("average_score")
    @classmethod
    def validate_average(cls, v: float) -> float:
        return _normalise_score(v)


class TopMoments(BaseModel):
    best_answer_question_id: str
    best_answer_quote: str
    weakest_answer_question_id: str
    weakest_answer_quote: str
    missed_opportunity_question_id: str
    missed_opportunity_summary: str

    @model_validator(mode="after")
    def validate_quotes(self, info: ValidationInfo) -> "TopMoments":
        allowed_quotes = set((info.context or {}).get("allowed_quotes", []))
        if allowed_quotes:
            for quote in (self.best_answer_quote, self.weakest_answer_quote):
                if not _is_grounded(quote, allowed_quotes, exact=True):
                    raise ValueError(f"Top moment quote is not grounded in transcript: {quote}")
        return self


class QuestionFeedback(BaseModel):
    question_id: str
    category: str
    question_text: str
    answer_quote: Optional[str] = None
    score: Optional[float] = None
    strength: Optional[str] = None
    improvement_area: Optional[str] = None
    suggested_rewrite: Optional[str] = None
    skipped: bool

    @field_validator("score")
    @classmethod
    def validate_score(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        return _normalise_score(v)

    @model_validator(mode="after")
    def validate_feedback(self, info: ValidationInfo) -> "QuestionFeedback":
        if self.skipped:
            if self.score is not None:
                raise ValueError("Skipped feedback must have score = null")
            return self

        required = {
            "answer_quote": self.answer_quote,
            "score": self.score,
            "strength": self.strength,
            "improvement_area": self.improvement_area,
            "suggested_rewrite": self.suggested_rewrite,
        }
        missing = [name for name, value in required.items() if value is None or value == ""]
        if missing:
            raise ValueError(f"Non-skipped feedback missing required fields: {missing}")

        allowed_quotes = set((info.context or {}).get("allowed_quotes", []))
        if allowed_quotes and self.answer_quote and not _is_grounded(
            self.answer_quote, allowed_quotes, exact=True
        ):
            raise ValueError(
                f"Question feedback quote is not grounded in transcript: {self.answer_quote}"
            )
        return self


class ActionItem(BaseModel):
    priority: int
    title: str
    why_it_matters: str
    example_from_session: str
    practice_instruction: str

    @field_validator("priority")
    @classmethod
    def priority_range(cls, v: int) -> int:
        if not (1 <= v <= 5):
            raise ValueError("Action item priority must be between 1 and 5")
        return v

    @model_validator(mode="after")
    def validate_grounding(self, info: ValidationInfo) -> "ActionItem":
        allowed_quotes = set((info.context or {}).get("allowed_quotes", []))
        if allowed_quotes and not _is_grounded(self.example_from_session, allowed_quotes):
            raise ValueError(
                f"Action item example is not grounded in transcript: {self.example_from_session}"
            )
        return self


class ReportData(BaseModel):
    session_id: str
    resume_name: str
    generated_at: str
    overall_score: float
    dimension_breakdown: DimensionBreakdown
    category_breakdown: list[CategoryScore]
    top_moments: TopMoments
    per_question_feedback: list[QuestionFeedback]
    action_items: list[ActionItem]

    @field_validator("overall_score")
    @classmethod
    def validate_overall_score(cls, v: float) -> float:
        return _normalise_score(v)

    @model_validator(mode="after")
    def validate_report(self, info: ValidationInfo) -> "ReportData":
        priorities = [item.priority for item in self.action_items]
        if sorted(priorities) != [1, 2, 3, 4, 5]:
            raise ValueError("ReportData.action_items must contain priorities 1 through 5")

        question_ids = set((info.context or {}).get("question_ids", []))
        expected_feedback = (info.context or {}).get("expected_feedback", {})
        expected_order = list((info.context or {}).get("feedback_order", []))
        if question_ids:
            feedback_ids = [item.question_id for item in self.per_question_feedback]
            unknown = [question_id for question_id in feedback_ids if question_id not in question_ids]
            if unknown:
                raise ValueError(f"Feedback contains unknown question IDs: {unknown}")

            if expected_order and feedback_ids != expected_order:
                raise ValueError(
                    "per_question_feedback must follow reached question order from the question bank"
                )

            for item in self.per_question_feedback:
                expected = expected_feedback.get(item.question_id)
                if not expected:
                    continue
                if item.category != expected["category"]:
                    raise ValueError(
                        f"Feedback category mismatch for {item.question_id}: {item.category}"
                    )
                if item.question_text != expected["question_text"]:
                    raise ValueError(f"Feedback question text mismatch for {item.question_id}")
                if item.skipped != expected["skipped"]:
                    raise ValueError(f"Feedback skipped flag mismatch for {item.question_id}")
                if item.score != expected["score"]:
                    raise ValueError(f"Feedback score mismatch for {item.question_id}")

            moment_ids = {
                self.top_moments.best_answer_question_id,
                self.top_moments.weakest_answer_question_id,
                self.top_moments.missed_opportunity_question_id,
            }
            unknown_moments = [question_id for question_id in moment_ids if question_id not in question_ids]
            if unknown_moments:
                raise ValueError(f"Top moments contain unknown question IDs: {unknown_moments}")

        return self
