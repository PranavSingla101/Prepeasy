from typing import Optional
from pydantic import BaseModel, field_validator


class Contact(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin: Optional[str] = None


class Skills(BaseModel):
    languages: list[str] = []
    frameworks: list[str] = []
    tools: list[str] = []


class Education(BaseModel):
    degree: str
    institution: str
    year: Optional[str] = None


class ExperienceEntry(BaseModel):
    company: str
    role: str
    duration_months: int
    has_metrics: bool
    vague_claims: list[str] = []

    @field_validator("duration_months", mode="before")
    @classmethod
    def coerce_duration(cls, v):
        # LLM occasionally returns a string like "6" instead of int
        return int(v)


class ResumeData(BaseModel):
    name: str
    contact: Contact
    skills: Skills
    education: Education
    experience: list[ExperienceEntry]
    gap_analysis: list[str]

    @field_validator("gap_analysis")
    @classmethod
    def gap_analysis_not_empty(cls, v):
        if not v:
            raise ValueError("gap_analysis must contain at least one observation")
        return v
