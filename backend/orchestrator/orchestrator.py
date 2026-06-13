import asyncio
import json
import logging
import os
import time
from pathlib import Path

from google import genai
from google.genai import types as genai_types

from backend.db.events import (
    EVT_DECISION_MADE,
    EVT_QUESTION_ASKED,
    EVT_SESSION_END,
    log_event,
)
from backend.scoring.scorer import score_answer_async
from backend.db.session import get_question_bank, save_transcript_entry
from backend.orchestrator.state import InterviewState
from backend.schemas.session import OrchestratorDecision, TranscriptEntry

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "interviewer_v1.txt"

# In-memory session state — keyed by session_id
_sessions: dict[str, InterviewState] = {}


def _client() -> genai.Client:
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start_session(session_id: str) -> str:
    """Load question bank, init state, return first question text."""
    bank = get_question_bank(session_id)
    state = InterviewState(session_id=session_id, question_bank=bank)
    _sessions[session_id] = state

    first_q = bank.questions[0]
    log_event(session_id, EVT_QUESTION_ASKED, {
        "question_id": first_q.id,
        "category": first_q.category,
        "text": first_q.text,
    })
    return first_q.text


def get_state(session_id: str) -> InterviewState | None:
    return _sessions.get(session_id)


def end_session(session_id: str) -> None:
    _sessions.pop(session_id, None)


def handle_silence(session_id: str) -> str | None:
    """Called by the silence timer when silence_streak >= 8. Returns nudge text."""
    state = _sessions.get(session_id)
    if state is None or not state.session_active:
        return None
    state.silence_streak = 0
    return "Take your time, or say 'skip' to move on."


async def handle_transcript(session_id: str, text: str) -> str:
    """Core decision function. Called on every final Deepgram transcript. Returns text to speak."""
    state = _sessions.get(session_id)
    if state is None or not state.session_active:
        return ""

    state.silence_streak = 0
    text_lower = text.lower()

    # --- Edge case: repeat request ---
    if "repeat" in text_lower or "say that again" in text_lower:
        return state.current_question.text

    # --- Edge case: skip request ---
    if "skip" in text_lower or "next question" in text_lower:
        return await _advance_question(state, skipped=True)

    # Append user turn to transcript log
    _append_entry(state, "user", text)

    # --- Edge case: one-word/two-word answer ---
    force_follow_up_vague = len(text.strip().split()) <= 2

    # --- Gemini decision ---
    prompt = _build_prompt(state, force_follow_up_vague)
    raw_response = await _call_gemini(prompt)

    try:
        decision = OrchestratorDecision.model_validate(json.loads(raw_response))
    except Exception as exc:
        logger.error("Gemini response validation failed. raw=%s error=%s", raw_response, exc)
        raise

    # Merge extracted key facts (dedup, preserve order)
    for fact in decision.key_facts:
        if fact and fact not in state.key_facts_mentioned:
            state.key_facts_mentioned.append(fact)

    # --- Follow-up cap guard (orchestrator enforces, not LLM) ---
    model_action = decision.action
    action = model_action
    if action in ("follow_up", "probe") and state.follow_up_count >= 2:
        action = "next_question"

    response_text = decision.text

    # Log decision metadata so raw model action vs final action are distinguishable
    log_event(session_id, EVT_DECISION_MADE, {
        "question_id": state.current_question_id,
        "model_action": model_action,
        "decision_action": action,
        "follow_up_count": state.follow_up_count,
    })

    if action in ("follow_up", "probe"):
        state.follow_up_count += 1
        _append_entry(state, "agent", response_text)
        return response_text

    if action == "next_question":
        return await _advance_question(state, preamble=response_text)

    if action == "close":
        state.session_active = False
        _append_entry(state, "agent", response_text)
        log_event(session_id, EVT_SESSION_END, {"reason": "close"})
        return response_text

    return response_text


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _advance_question(
    state: InterviewState,
    skipped: bool = False,
    preamble: str = "",
) -> str:
    completed_idx = state.current_question_idx
    completed_q = state.question_bank.questions[completed_idx]

    # Gather transcript for the completed question before advancing the index
    answer_transcript = [
        e for e in state.transcript_log if e.question_id == completed_q.id
    ]

    has_next = state.current_question_idx < len(state.question_bank.questions) - 1

    if has_next:
        state.current_question_idx += 1
        state.follow_up_count = 0
        next_q = state.question_bank.questions[state.current_question_idx]

        # Fire async scoring for the completed question (non-blocking)
        asyncio.create_task(_score_answer(
            state.session_id, completed_q.id, completed_q.text, completed_q.category,
            answer_transcript, skipped
        ))

        response_text = (preamble + " " if preamble else "") + next_q.text
        response_text = response_text.strip()
        _append_entry(state, "agent", response_text)
        log_event(state.session_id, EVT_QUESTION_ASKED, {
            "question_id": next_q.id,
            "category": next_q.category,
            "text": next_q.text,
        })
        return response_text
    else:
        # Last question done — close session
        state.session_active = False
        closing = (
            preamble
            or "That wraps up our interview. Thank you so much for your time. We'll be in touch soon."
        )
        _append_entry(state, "agent", closing)

        asyncio.create_task(_score_answer(
            state.session_id, completed_q.id, completed_q.text, completed_q.category,
            answer_transcript, skipped
        ))
        log_event(state.session_id, EVT_SESSION_END, {"reason": "all_questions_complete"})
        return closing


def _append_entry(state: InterviewState, speaker: str, text: str) -> None:
    entry = TranscriptEntry(
        speaker=speaker,  # type: ignore[arg-type]
        text=text,
        question_id=state.current_question_id,
        ts=time.time(),
    )
    state.transcript_log.append(entry)
    save_transcript_entry(state.session_id, entry)


def _build_prompt(state: InterviewState, force_follow_up_vague: bool) -> str:
    template = _load_prompt()
    q = state.current_question

    history_lines = [
        f"{e.speaker.upper()}: {e.text}" for e in state.transcript_log
    ]
    history = "\n".join(history_lines) or "(no prior turns)"
    key_facts = ", ".join(state.key_facts_mentioned) or "none"

    extra_constraint = ""
    if force_follow_up_vague:
        extra_constraint = (
            "CONSTRAINT: The user's answer was only one or two words. "
            "You MUST return action='follow_up' using follow_up_vague. "
            "Do NOT return next_question."
        )

    return template.format(
        question_id=q.id,
        question_category=q.category,
        question_source_ref=q.source_ref,
        current_question=q.text,
        follow_up_vague=q.follow_up_vague,
        follow_up_strong=q.follow_up_strong,
        conversation_history=history,
        key_facts=key_facts,
        follow_up_count=state.follow_up_count,
        current_question_idx=state.current_question_idx,
        total_questions=len(state.question_bank.questions),
        extra_constraint=extra_constraint,
    )


async def _call_gemini(prompt: str) -> str:
    client = _client()
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        ),
    )
    return response.text


async def _score_answer(
    session_id: str,
    question_id: str,
    question_text: str,
    question_category: str,
    transcript: list[TranscriptEntry],
    skipped: bool = False,
) -> None:
    await score_answer_async(
        session_id, question_id, question_text, question_category, transcript, skipped
    )
