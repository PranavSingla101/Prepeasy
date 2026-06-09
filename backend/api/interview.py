"""FastAPI WebSocket endpoint for the live interview session.

Route: ws://localhost:8000/ws/interview/{session_id}

On connect: validates session, initialises the orchestrator, starts the pipeline.
On binary frame: raw PCM audio forwarded to the pipeline.
On text frame: JSON control messages dispatched to control handler.
On disconnect: cleans up pipeline and logs session_end event.
"""
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.db.events import EVT_SESSION_END, log_event
from backend.db.session import get_question_bank
from backend.orchestrator import orchestrator
from backend.voice_pipeline.pipeline import InterviewPipeline

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/interview/{session_id}")
async def interview_websocket(websocket: WebSocket, session_id: str) -> None:
    # Validate that a question bank exists for this session before accepting
    try:
        get_question_bank(session_id)
    except KeyError:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    logger.info("WebSocket connected: session_id=%s", session_id)

    # Initialise orchestrator state, get first question text
    first_question_text = orchestrator.start_session(session_id)

    # Start the pipeline — blocks until session ends or WebSocket closes
    pipeline = InterviewPipeline(session_id=session_id, websocket=websocket)
    try:
        await pipeline.start(first_question_text)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("Pipeline error session=%s: %s", session_id, exc)
    finally:
        orchestrator.end_session(session_id)
        log_event(session_id, EVT_SESSION_END, {"reason": "websocket_disconnect"})
        logger.info("Session ended: session_id=%s", session_id)
