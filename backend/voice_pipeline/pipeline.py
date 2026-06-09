"""Pipeline assembly and lifecycle.

Wires WebSocket transport → Silero VAD → Deepgram STT → event bus → Orchestrator → TTS → WebSocket.

Alignment rule: this file must NEVER import from backend.orchestrator.
All cross-boundary state reads and calls go through backend.voice_pipeline.events.
"""
import asyncio
import logging
import time

from fastapi import WebSocket

from backend.voice_pipeline import events as event_bus
from backend.voice_pipeline.stt import STTSession
from backend.voice_pipeline.transport import WebSocketTransport
from backend.voice_pipeline.tts import TTSSession
from backend.voice_pipeline.vad import VADProcessor

logger = logging.getLogger(__name__)

# Active pipelines keyed by session_id
_pipelines: dict[str, "InterviewPipeline"] = {}


def get_pipeline(session_id: str) -> "InterviewPipeline | None":
    return _pipelines.get(session_id)


class InterviewPipeline:
    """Per-session pipeline that owns all voice I/O components."""

    def __init__(self, session_id: str, websocket: WebSocket) -> None:
        self._session_id = session_id
        self._first_audio_received = asyncio.Event()

        # TTS must be created before transport (send_audio callback reference)
        self._tts = TTSSession(
            session_id=session_id,
            send_audio=self._send_audio_to_browser,
        )
        self._transport = WebSocketTransport(
            websocket=websocket,
            on_audio=self._on_audio_frame,
            on_control=self._on_control,
        )
        self._stt = STTSession(
            session_id=session_id,
            on_transcript=self._on_transcript,
            get_question_id=lambda: event_bus.get_current_question_id(session_id),
        )
        self._vad = VADProcessor(
            session_id=session_id,
            on_speech_start=self._on_speech_start,
            on_speech_end=self._on_speech_end,
        )
        self._silence_task: asyncio.Task | None = None
        self._tts_start_ts: float = 0.0

    @property
    def is_speaking(self) -> bool:
        return self._tts.is_speaking

    async def start(self, first_question_text: str) -> None:
        """Initialise components, speak opening question, and block until the session ends."""
        self._vad.set_question_id(event_bus.get_current_question_id(self._session_id))
        await self._stt.start()

        _pipelines[self._session_id] = self
        self._silence_task = asyncio.create_task(self._silence_timer())

        receive_task = asyncio.create_task(self._transport.receive_loop())
        try:
            # Wait up to 10 s for the first audio frame before speaking
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._first_audio_received.wait()), timeout=10.0
                )
            except asyncio.TimeoutError:
                pass

            await self._speak(event_bus.get_current_question_id(self._session_id), first_question_text)
            await receive_task
        finally:
            await self._cleanup()

    async def _cleanup(self) -> None:
        if self._silence_task:
            self._silence_task.cancel()
            try:
                await self._silence_task
            except asyncio.CancelledError:
                pass
        await self._stt.stop()
        _pipelines.pop(self._session_id, None)

    # ---------------------------------------------------------------------------
    # Audio I/O
    # ---------------------------------------------------------------------------

    async def _send_audio_to_browser(self, audio_bytes: bytes) -> None:
        await self._transport.send_audio(audio_bytes)

    async def _on_audio_frame(self, pcm_chunk: bytes) -> None:
        self._first_audio_received.set()
        await self._stt.send_audio(pcm_chunk)
        await self._vad.process(pcm_chunk)

    # ---------------------------------------------------------------------------
    # VAD callbacks
    # ---------------------------------------------------------------------------

    def _on_speech_start(self) -> None:
        event_bus.reset_silence_streak(self._session_id)
        if self._tts.is_speaking:
            elapsed_ms = int((time.time() - self._tts_start_ts) * 1000)
            self._tts.barge_in(
                event_bus.get_current_question_id(self._session_id), elapsed_ms
            )
        self._stt.begin_speech()

    async def _on_speech_end(self, duration_ms: int) -> None:
        await self._stt.end_speech()

    # ---------------------------------------------------------------------------
    # STT → Orchestrator → TTS
    # ---------------------------------------------------------------------------

    async def _on_transcript(self, text: str) -> None:
        if not event_bus.is_session_active(self._session_id):
            return
        await self._transport.send_transcript("user", text)
        response_text = await event_bus.dispatch_transcript(self._session_id, text)
        if response_text:
            question_id = event_bus.get_current_question_id(self._session_id)
            self._vad.set_question_id(question_id)
            await self._transport.send_transcript("agent", response_text)
            await self._speak(question_id, response_text)

    async def _speak(self, question_id: str, text: str) -> None:
        self._tts_start_ts = time.time()
        await self._tts.speak(question_id, text)

    # ---------------------------------------------------------------------------
    # Control messages
    # ---------------------------------------------------------------------------

    async def _on_control(self, payload: dict) -> None:
        action = payload.get("action", "")
        if action == "skip":
            await self._on_transcript("skip")
        elif action == "repeat":
            await self._on_transcript("repeat")
        elif action == "end_session":
            event_bus.reset_silence_streak(self._session_id)
            event_bus.deactivate_session(self._session_id)

    # ---------------------------------------------------------------------------
    # Silence timer
    # ---------------------------------------------------------------------------

    async def _silence_timer(self) -> None:
        try:
            while event_bus.is_session_active(self._session_id):
                await asyncio.sleep(1)
                if self._tts.is_speaking:
                    continue
                streak = event_bus.increment_silence_streak(self._session_id)
                if streak >= 8:
                    nudge = event_bus.dispatch_silence(self._session_id)
                    if nudge:
                        question_id = event_bus.get_current_question_id(self._session_id)
                        await self._transport.send_transcript("agent", nudge)
                        await self._speak(question_id, nudge)
        except asyncio.CancelledError:
            pass
