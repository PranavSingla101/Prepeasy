import asyncio
import json
import logging
import os
import time
from pathlib import Path

from google import genai
from google.genai import types as genai_types

from backend.db.events import EVT_SCORING_COMPLETE, log_event
from backend.db.session import save_score
from backend.schemas.scoring import ScoreResult
from backend.schemas.session import TranscriptEntry

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "scoring_v1.txt"


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _client() -> genai.Client:
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


async def score_answer_async(
    session_id: str,
    question_id: str,
    question_text: str,
    question_category: str,
    transcript: list[TranscriptEntry],
    skipped: bool = False,
) -> None:
    """Score one answer non-blockingly. Never raises — failures are logged and swallowed."""
    try:
        user_turns = [e for e in transcript if e.speaker == "user"]
        answer_transcript = "\n".join(e.text for e in user_turns) or "(no answer)"

        prompt = _load_prompt().format(
            question_text=question_text,
            question_category=question_category,
            answer_transcript=answer_transcript,
            is_skipped="true" if skipped else "false",
        )

        gemini_start = time.time()
        loop = asyncio.get_event_loop()
        response_text = await loop.run_in_executor(
            None,
            lambda: _client().models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            ).text,
        )
        scoring_duration_ms = int((time.time() - gemini_start) * 1000)

        try:
            raw = json.loads(response_text)
            raw["question_id"] = question_id
            raw["skipped"] = skipped
            score_result = ScoreResult.model_validate(raw)
        except Exception as exc:
            logger.error(
                "ScoreResult validation failed: session=%s question=%s error=%s raw=%s",
                session_id, question_id, exc, response_text,
            )
            log_event(session_id, EVT_SCORING_COMPLETE, {
                "question_id": question_id,
                "error": "validation_failed",
                "scoring_duration_ms": scoring_duration_ms,
            })
            return

        try:
            save_score(session_id, question_id, score_result)
        except Exception as exc:
            logger.error(
                "save_score failed: session=%s question=%s error=%s",
                session_id, question_id, exc,
            )
            log_event(session_id, EVT_SCORING_COMPLETE, {
                "question_id": question_id,
                "error": "save_failed",
                "scoring_duration_ms": scoring_duration_ms,
            })
            return

        log_event(session_id, EVT_SCORING_COMPLETE, {
            "question_id": question_id,
            "overall": score_result.overall,
            "skipped": score_result.skipped,
            "scoring_duration_ms": scoring_duration_ms,
        })

    except Exception as exc:
        logger.error(
            "score_answer_async unexpected error: session=%s question=%s error=%s",
            session_id, question_id, exc,
        )
