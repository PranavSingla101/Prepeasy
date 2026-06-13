import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from google import genai
from google.genai import types as genai_types

from backend.db.session import get_question_bank, get_scores, get_transcripts
from backend.schemas.questions import Question
from backend.schemas.report import ReportData
from backend.schemas.scoring import ScoreResult
from backend.schemas.session import TranscriptEntry

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "report_v1.txt"


class ReportSynthesisError(RuntimeError):
    """Raised when report synthesis inputs or LLM output are invalid."""


def _client() -> genai.Client:
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def synthesize_report(session_id: str) -> ReportData:
    bank = get_question_bank(session_id)
    scores = get_scores(session_id)
    transcripts = get_transcripts(session_id)

    if not scores:
        raise ReportSynthesisError(f"No score rows found for session_id '{session_id}'")
    if not transcripts:
        raise ReportSynthesisError(f"No transcript rows found for session_id '{session_id}'")

    questions_by_id = {question.id: question for question in bank.questions}
    scores_by_id = _validate_scores(scores, questions_by_id)
    transcripts_by_question = _group_transcripts(transcripts)
    _validate_transcripts(transcripts_by_question, questions_by_id)
    reached_question_ids = _reached_question_ids(bank.questions, scores_by_id, transcripts_by_question)
    _validate_missing_scores(reached_question_ids, scores_by_id)

    aggregates = _build_aggregates(bank.questions, scores_by_id, reached_question_ids)
    allowed_quotes = _allowed_quotes(reached_question_ids, transcripts_by_question)
    if not allowed_quotes:
        raise ReportSynthesisError("No user transcript quotes available for report grounding")

    prompt = _build_prompt(
        session_id=session_id,
        resume_name=bank.resume_name,
        questions=bank.questions,
        scores_by_id=scores_by_id,
        transcripts_by_question=transcripts_by_question,
        reached_question_ids=reached_question_ids,
        aggregates=aggregates,
        allowed_quotes=allowed_quotes,
    )
    raw_response = _call_gemini(prompt)

    try:
        narrative = json.loads(raw_response)
        data = {
            "session_id": session_id,
            "resume_name": bank.resume_name,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            **aggregates,
            **narrative,
        }
        return ReportData.model_validate(
            data,
            context={
                "question_ids": set(questions_by_id),
                "allowed_quotes": set(allowed_quotes),
                "feedback_order": reached_question_ids,
                "expected_feedback": _expected_feedback(
                    bank.questions, scores_by_id, reached_question_ids
                ),
            },
        )
    except Exception as exc:
        logger.error("ReportData validation failed. raw=%s error=%s", raw_response, exc)
        raise ReportSynthesisError("Report synthesis validation failed") from exc


def _validate_scores(
    scores: list[ScoreResult], questions_by_id: dict[str, Question]
) -> dict[str, ScoreResult]:
    scores_by_id: dict[str, ScoreResult] = {}
    for score in scores:
        if score.question_id not in questions_by_id:
            raise ReportSynthesisError(
                f"Score references unknown question_id '{score.question_id}'"
            )
        if score.question_id in scores_by_id:
            raise ReportSynthesisError(f"Duplicate score for question_id '{score.question_id}'")
        scores_by_id[score.question_id] = score
    return scores_by_id


def _group_transcripts(
    transcripts: list[TranscriptEntry],
) -> dict[str, list[TranscriptEntry]]:
    grouped: dict[str, list[TranscriptEntry]] = defaultdict(list)
    for entry in transcripts:
        grouped[entry.question_id].append(entry)
    return dict(grouped)


def _validate_transcripts(
    transcripts_by_question: dict[str, list[TranscriptEntry]],
    questions_by_id: dict[str, Question],
) -> None:
    unknown = [
        question_id
        for question_id, entries in transcripts_by_question.items()
        if entries and question_id not in questions_by_id
    ]
    if unknown:
        raise ReportSynthesisError(
            f"Transcript references unknown question_id values: {unknown}"
        )


def _reached_question_ids(
    questions: list[Question],
    scores_by_id: dict[str, ScoreResult],
    transcripts_by_question: dict[str, list[TranscriptEntry]],
) -> list[str]:
    reached = {
        question_id
        for question_id, entries in transcripts_by_question.items()
        if entries
    }
    reached.update(scores_by_id)
    ordered_ids = [question.id for question in questions]
    return [question_id for question_id in ordered_ids if question_id in reached]


def _validate_missing_scores(
    reached_question_ids: list[str], scores_by_id: dict[str, ScoreResult]
) -> None:
    missing = [question_id for question_id in reached_question_ids if question_id not in scores_by_id]
    if missing:
        raise ReportSynthesisError(f"Missing score rows for reached questions: {missing}")


def _build_aggregates(
    questions: list[Question],
    scores_by_id: dict[str, ScoreResult],
    reached_question_ids: list[str],
) -> dict:
    non_skipped = [
        scores_by_id[question_id]
        for question_id in reached_question_ids
        if not scores_by_id[question_id].skipped
    ]
    if not non_skipped:
        raise ReportSynthesisError("Cannot synthesize report with no non-skipped answers")

    def average(values: list[float | int]) -> float:
        return round(sum(float(value) for value in values) / len(values), 1)

    question_by_id = {question.id: question for question in questions}
    by_category: dict[str, list[ScoreResult]] = defaultdict(list)
    skipped_by_category: dict[str, int] = defaultdict(int)

    for question_id in reached_question_ids:
        score = scores_by_id[question_id]
        category = question_by_id[question_id].category
        if score.skipped:
            skipped_by_category[category] += 1
        else:
            by_category[category].append(score)

    category_breakdown = []
    for category in sorted(set(by_category) | set(skipped_by_category)):
        answered = by_category.get(category, [])
        if answered:
            average_score = average([score.overall for score in answered if score.overall is not None])
        else:
            average_score = 1.0
        category_breakdown.append({
            "category": category,
            "average_score": average_score,
            "answered_count": len(answered),
            "skipped_count": skipped_by_category.get(category, 0),
        })

    return {
        "overall_score": average([score.overall for score in non_skipped if score.overall is not None]),
        "dimension_breakdown": {
            "relevance": average([score.relevance for score in non_skipped if score.relevance is not None]),
            "specificity": average([score.specificity for score in non_skipped if score.specificity is not None]),
            "structure": average([score.structure for score in non_skipped if score.structure is not None]),
            "communication": average([score.communication for score in non_skipped if score.communication is not None]),
        },
        "category_breakdown": category_breakdown,
    }


def _expected_feedback(
    questions: list[Question],
    scores_by_id: dict[str, ScoreResult],
    reached_question_ids: list[str],
) -> dict[str, dict]:
    question_by_id = {question.id: question for question in questions}
    expected = {}
    for question_id in reached_question_ids:
        question = question_by_id[question_id]
        score = scores_by_id[question_id]
        expected[question_id] = {
            "category": question.category,
            "question_text": question.text,
            "score": score.overall,
            "skipped": score.skipped,
        }
    return expected


def _allowed_quotes(
    reached_question_ids: list[str],
    transcripts_by_question: dict[str, list[TranscriptEntry]],
) -> list[str]:
    quotes: list[str] = []
    for question_id in reached_question_ids:
        for entry in transcripts_by_question.get(question_id, []):
            if entry.speaker == "user" and entry.text.strip():
                quotes.append(entry.text.strip())
    return quotes


def _build_prompt(
    session_id: str,
    resume_name: str,
    questions: list[Question],
    scores_by_id: dict[str, ScoreResult],
    transcripts_by_question: dict[str, list[TranscriptEntry]],
    reached_question_ids: list[str],
    aggregates: dict,
    allowed_quotes: list[str],
) -> str:
    question_by_id = {question.id: question for question in questions}
    feedback_inputs = []
    for question_id in reached_question_ids:
        question = question_by_id[question_id]
        score = scores_by_id[question_id]
        user_quotes = [
            entry.text.strip()
            for entry in transcripts_by_question.get(question_id, [])
            if entry.speaker == "user" and entry.text.strip()
        ]
        feedback_inputs.append({
            "question_id": question.id,
            "category": question.category,
            "question_text": question.text,
            "score": score.model_dump(),
            "candidate_quotes": user_quotes,
            "agent_context": [
                entry.text.strip()
                for entry in transcripts_by_question.get(question_id, [])
                if entry.speaker == "agent" and entry.text.strip()
            ],
        })

    replacements = {
        "{session_id}": session_id,
        "{resume_name}": resume_name,
        "{score_summary}": json.dumps(aggregates, indent=2),
        "{question_feedback_inputs}": json.dumps(feedback_inputs, indent=2),
        "{allowed_quotes}": json.dumps(allowed_quotes, indent=2),
    }
    prompt = _load_prompt()
    for placeholder, value in replacements.items():
        prompt = prompt.replace(placeholder, value)
    return prompt


def _call_gemini(prompt: str) -> str:
    response = _client().models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )
    return response.text
