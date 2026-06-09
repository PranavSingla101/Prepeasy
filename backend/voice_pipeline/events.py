"""Event bus — wires voice pipeline output to orchestrator input.

The voice pipeline must never import from backend.orchestrator directly.
This module is the only authorised crossing point: it calls the orchestrator's
public functions and exposes thin state-read helpers so the pipeline never
needs to touch orchestrator internals.
"""
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Transcript / silence dispatch
# ---------------------------------------------------------------------------

async def dispatch_transcript(session_id: str, text: str) -> str:
    """Forward a final transcript to the orchestrator and return the response text."""
    from backend.orchestrator import orchestrator
    return await orchestrator.handle_transcript(session_id, text)


def dispatch_silence(session_id: str) -> str | None:
    """Forward a silence tick to the orchestrator and return nudge text (or None)."""
    from backend.orchestrator import orchestrator
    return orchestrator.handle_silence(session_id)


# ---------------------------------------------------------------------------
# State accessors — pipeline reads orchestrator state through here only
# ---------------------------------------------------------------------------

def get_current_question_id(session_id: str) -> str:
    from backend.orchestrator import orchestrator
    state = orchestrator.get_state(session_id)
    return state.current_question_id if state else ""


def is_session_active(session_id: str) -> bool:
    from backend.orchestrator import orchestrator
    state = orchestrator.get_state(session_id)
    return state.session_active if state else False


def reset_silence_streak(session_id: str) -> None:
    from backend.orchestrator import orchestrator
    state = orchestrator.get_state(session_id)
    if state:
        state.silence_streak = 0


def increment_silence_streak(session_id: str) -> int:
    """Increment and return the new silence streak value."""
    from backend.orchestrator import orchestrator
    state = orchestrator.get_state(session_id)
    if state:
        state.silence_streak += 1
        return state.silence_streak
    return 0


def deactivate_session(session_id: str) -> None:
    """Mark the session as inactive (e.g. on end_session control message)."""
    from backend.orchestrator import orchestrator
    state = orchestrator.get_state(session_id)
    if state:
        state.session_active = False
