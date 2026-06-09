"""Google AI Studio TTS wrapper with barge-in (interrupt) detection.

speak() is called by the pipeline after the orchestrator returns a response text.
Streams TTS audio over the WebSocket and handles barge-in cancellation.
Never contains interview logic.
"""
import asyncio
import base64
import logging
import os
import time
from typing import Callable, Awaitable

from google import genai
from google.genai import types as genai_types

from backend.db.events import EVT_INTERRUPTION, EVT_TTS_COMPLETE, log_event

logger = logging.getLogger(__name__)

_TTS_MODEL = "gemini-2.5-flash-preview-tts"
_VOICE_NAME = "Aoede"


class TTSSession:
    """Manages TTS playback state for one interview session."""

    def __init__(
        self,
        session_id: str,
        send_audio: Callable[[bytes], Awaitable[None]],
    ) -> None:
        self._session_id = session_id
        self._send_audio = send_audio
        self._speaking = False
        self._cancel_event = asyncio.Event()

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    def barge_in(self, question_id: str, elapsed_ms: int) -> None:
        """User started speaking mid-TTS. Cancel current stream."""
        if self._speaking:
            log_event(self._session_id, EVT_INTERRUPTION, {
                "question_id": question_id,
                "tts_elapsed_ms": elapsed_ms,
            })
            self._cancel_event.set()

    async def speak(self, question_id: str, text: str) -> None:
        """Convert text to audio via Gemini TTS and stream it to the browser."""
        self._speaking = True
        self._cancel_event.clear()
        speak_start_ts = time.time()
        first_chunk_ts: float | None = None

        try:
            client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

            # Run blocking generate_content_stream in executor to avoid blocking event loop
            loop = asyncio.get_event_loop()

            def _stream():
                return client.models.generate_content_stream(
                    model=_TTS_MODEL,
                    contents=[{"parts": [{"text": text}]}],
                    config=genai_types.GenerateContentConfig(
                        response_modalities=["AUDIO"],
                        speech_config=genai_types.SpeechConfig(
                            voice_config=genai_types.VoiceConfig(
                                prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                                    voice_name=_VOICE_NAME,
                                )
                            )
                        ),
                    ),
                )

            chunks_iter = await loop.run_in_executor(None, _stream)

            for chunk in chunks_iter:
                if self._cancel_event.is_set():
                    break

                if first_chunk_ts is None:
                    first_chunk_ts = time.time()

                # Extract audio bytes from the response chunk
                audio_bytes = _extract_audio(chunk)
                if audio_bytes:
                    await self._send_audio(audio_bytes)

                # Yield control so barge-in events can be processed
                await asyncio.sleep(0)

            if not self._cancel_event.is_set():
                ttfa_ms = int((first_chunk_ts - speak_start_ts) * 1000) if first_chunk_ts else 0
                total_ms = int((time.time() - speak_start_ts) * 1000)
                log_event(self._session_id, EVT_TTS_COMPLETE, {
                    "question_id": question_id,
                    "ttfa_ms": ttfa_ms,
                    "total_duration_ms": total_ms,
                })
        except Exception as exc:
            logger.error("TTS speak() error: %s", exc)
        finally:
            self._speaking = False


def _extract_audio(chunk) -> bytes | None:
    """Pull raw audio bytes from a Gemini generate_content_stream chunk."""
    try:
        for part in chunk.candidates[0].content.parts:
            if hasattr(part, "inline_data") and part.inline_data:
                data = part.inline_data.data
                # Gemini returns base64-encoded audio
                if isinstance(data, str):
                    return base64.b64decode(data)
                if isinstance(data, bytes):
                    return data
    except (AttributeError, IndexError, TypeError):
        pass
    return None
