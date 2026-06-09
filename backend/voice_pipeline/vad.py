"""Silero VAD integration with event emission.

Receives raw PCM chunks from the WebSocket transport.
Fires vad_start / vad_end events and signals the STT layer when to buffer audio.
"""
import logging
import time
from typing import Callable, Awaitable

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams, VADState

from backend.db.events import EVT_VAD_END, EVT_VAD_START, log_event

logger = logging.getLogger(__name__)

_SAMPLE_RATE = 16000
_BYTES_PER_SAMPLE = 2  # 16-bit PCM
# Silero requires exactly 512 frames at 16kHz
_FRAME_SAMPLES = 512
_FRAME_BYTES = _FRAME_SAMPLES * _BYTES_PER_SAMPLE


class VADProcessor:
    """Stateful per-session VAD processor wrapping Pipecat's SileroVADAnalyzer."""

    def __init__(
        self,
        session_id: str,
        on_speech_start: Callable[[], None],
        on_speech_end: Callable[[int], Awaitable[None]],
    ) -> None:
        self._session_id = session_id
        self._on_speech_start = on_speech_start
        self._on_speech_end = on_speech_end

        self._analyzer = SileroVADAnalyzer(
            sample_rate=_SAMPLE_RATE,
            params=VADParams(stop_secs=0.8),  # 800ms silence threshold per spec
        )
        self._buf = b""
        self._prev_state: VADState = VADState.QUIET
        self._speech_start_ts: float = 0.0
        self._current_question_id: str = ""

    def set_question_id(self, question_id: str) -> None:
        self._current_question_id = question_id

    async def process(self, pcm_chunk: bytes) -> None:
        """Feed raw PCM bytes into the VAD. May fire on_speech_start / on_speech_end."""
        self._buf += pcm_chunk

        while len(self._buf) >= _FRAME_BYTES:
            frame = self._buf[:_FRAME_BYTES]
            self._buf = self._buf[_FRAME_BYTES:]
            new_state = await self._analyzer.analyze_audio(frame)
            await self._handle_transition(new_state)

    async def _handle_transition(self, new_state: VADState) -> None:
        prev = self._prev_state
        self._prev_state = new_state

        # QUIET/STARTING → SPEAKING: speech confirmed
        if prev != VADState.SPEAKING and new_state == VADState.SPEAKING:
            self._speech_start_ts = time.time()
            log_event(self._session_id, EVT_VAD_START, {
                "question_id": self._current_question_id,
            })
            self._on_speech_start()

        # SPEAKING/STOPPING → QUIET: silence confirmed
        elif prev in (VADState.SPEAKING, VADState.STOPPING) and new_state == VADState.QUIET:
            duration_ms = int((time.time() - self._speech_start_ts) * 1000)
            log_event(self._session_id, EVT_VAD_END, {
                "question_id": self._current_question_id,
                "speech_duration_ms": duration_ms,
            })
            await self._on_speech_end(duration_ms)
