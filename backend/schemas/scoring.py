from typing import Optional

from pydantic import BaseModel, field_validator, model_validator


class ScoreResult(BaseModel):
    question_id: str
    skipped: bool
    relevance: Optional[int] = None
    specificity: Optional[int] = None
    structure: Optional[int] = None
    communication: Optional[int] = None
    overall: Optional[float] = None
    strongest_moment: Optional[str] = None
    weakest_moment: Optional[str] = None
    suggested_rewrite: Optional[str] = None

    @field_validator("relevance", "specificity", "structure", "communication", mode="before")
    @classmethod
    def coerce_and_validate_score(cls, v: object) -> Optional[int]:
        if v is None:
            return None
        v_int = int(float(v))
        if not (1 <= v_int <= 10):
            raise ValueError(f"Score must be between 1 and 10, got {v_int}")
        return v_int

    @field_validator("strongest_moment", "weakest_moment", mode="after")
    @classmethod
    def non_empty_string(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        stripped = v.strip()
        if not stripped:
            raise ValueError("Must be a non-empty string or null")
        return stripped

    @model_validator(mode="after")
    def check_skipped_and_compute_overall(self) -> "ScoreResult":
        if self.skipped:
            numeric_fields = [self.relevance, self.specificity, self.structure, self.communication]
            text_fields = [self.strongest_moment, self.weakest_moment, self.suggested_rewrite]
            if any(f is not None for f in numeric_fields + text_fields):
                raise ValueError(
                    "Skipped answers must have null for all score and text fields"
                )
            self.overall = None
        else:
            dims = [self.relevance, self.specificity, self.structure, self.communication]
            if all(d is not None for d in dims):
                self.overall = round(sum(dims) / len(dims), 1)
            else:
                self.overall = None
        return self
