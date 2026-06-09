import json
import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

from backend.schemas.questions import QuestionBank
from backend.schemas.resume import ResumeData

load_dotenv()

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "questions_v1.txt"
_PROMPT_TEMPLATE = _PROMPT_PATH.read_text(encoding="utf-8")

_MODEL = "gemini-2.5-flash"


def _build_experience_block(resume: ResumeData) -> str:
    lines = []
    for exp in resume.experience:
        metrics_str = "Yes" if exp.has_metrics else "No"
        lines.append(
            f"  Company: {exp.company} | Role: {exp.role} | "
            f"Duration: {exp.duration_months} months | Metrics: {metrics_str}"
        )
        if exp.vague_claims:
            claims = " | ".join(f'"{c}"' for c in exp.vague_claims)
            lines.append(f"  Vague bullets: {claims}")
    return "\n".join(lines)


def _build_gap_analysis_block(resume: ResumeData) -> str:
    return "\n".join(
        f"  Gap {i + 1}: {item}" for i, item in enumerate(resume.gap_analysis)
    )


def generate_question_bank(resume: ResumeData, session_id: str) -> QuestionBank:
    """Generate 28 personalized interview questions from a validated ResumeData object."""
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    prompt = (
        _PROMPT_TEMPLATE
        .replace("{candidate_name}", resume.name)
        .replace("{experience_block}", _build_experience_block(resume))
        .replace("{skills_languages}", ", ".join(resume.skills.languages) or "None listed")
        .replace("{skills_frameworks}", ", ".join(resume.skills.frameworks) or "None listed")
        .replace("{skills_tools}", ", ".join(resume.skills.tools) or "None listed")
        .replace("{gap_analysis_block}", _build_gap_analysis_block(resume))
    )

    response = client.models.generate_content(
        model=_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.7,
        ),
    )

    raw = response.text.strip()
    # Strip markdown fences if model wraps output despite mime type
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[generator] Raw Gemini output:\n{raw}")
        raise

    # Gemini may return the array wrapped in an object key
    if isinstance(parsed, dict):
        for key in ("questions", "question_bank", "data"):
            if key in parsed and isinstance(parsed[key], list):
                parsed = parsed[key]
                break

    payload = {
        "session_id": session_id,
        "resume_name": resume.name,
        "questions": parsed,
    }

    try:
        bank = QuestionBank.model_validate(payload)
    except Exception as exc:
        print(f"[generator] Pydantic validation failed. Raw output:\n{raw}")
        raise

    return bank
