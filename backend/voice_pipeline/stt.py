"""Deepgram Nova-3 streaming STT integration.

Opens a persistent WebSocket to Deepgram at session start.
Streams audio during active speech windows and emits transcript_received events
on final transcripts. Never calls Gemini or examines the question bank.
"""
import asyncio
import logging
import os
import time
from typing import Callable, Awaitable

from deepgram import AsyncDeepgramClient
from deepgram.listen.v1.types.listen_v1results import ListenV1Results

from backend.db.events import EVT_TRANSCRIPT_RECEIVED, log_event

logger = logging.getLogger(__name__)


class STTSession:
    """Manages one Deepgram streaming connection per interview session."""

    def __init__(
        self,
        session_id: str,
        on_transcript: Callable[[str], Awaitable[None]],
        get_question_id: Callable[[], str],
    ) -> None:
        self._session_id = session_id
        self._on_transcript = on_transcript
        self._get_question_id = get_question_id

        self._client = AsyncDeepgramClient(api_key=os.environ["DEEPGRAM_API_KEY"])
        self._socket = None
        self._ctx_mgr = None
        self._listen_task: asyncio.Task | None = None

        self._vad_end_ts: float = 0.0
        self._is_streaming: bool = False

    async def start(self) -> None:
        """Open Deepgram WebSocket and start the receive loop."""
        self._ctx_mgr = self._client.listen.v1.connect(
            model="nova-3",
            encoding="linear16",
            sample_rate=16000,
            channels=1,
            interim_results=False,
            punctuate=True,
        )
        self._socket = await self._ctx_mgr.__aenter__()
        self._listen_task = asyncio.create_task(self._receive_loop())

    async def stop(self) -> None:
        """Close the Deepgram connection cleanly."""
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        if self._socket:
            try:
                await self._socket.send_close_stream()
            except Exception:
                pass
        if self._ctx_mgr:
            try:
                await self._ctx_mgr.__aexit__(None, None, None)
            except Exception:
                pass

    def begin_speech(self) -> None:
        """VAD signalled speech start — begin forwarding audio."""
        self._is_streaming = True

    async def end_speech(self) -> None:
        """VAD signalled speech end — finalize the current utterance."""
        self._vad_end_ts = time.time()
        self._is_streaming = False
        if self._socket:
            try:
                await self._socket.send_finalize()
            except Exception as exc:
                logger.warning("send_finalize failed: %s", exc)

    async def send_audio(self, pcm_chunk: bytes) -> None:
        """Forward a PCM chunk to Deepgram (only while speech is active)."""
        if self._is_streaming and self._socket:
            try:
                await self._socket.send_media(pcm_chunk)
            except Exception as exc:
                logger.warning("send_media failed: %s", exc)

    async def _receive_loop(self) -> None:
        """Listen for final transcripts from Deepgram and dispatch them."""
        if self._socket is None:
            return
        try:
            async for message in self._socket:
                if isinstance(message, ListenV1Results) and message.is_final:
                    alternatives = message.channel.alternatives
                    if not alternatives:
                        continue
                    text = alternatives[0].transcript.strip()
                    if not text:
                        continue

                    latency_ms = int((time.time() - self._vad_end_ts) * 1000)
                    question_id = self._get_question_id()

                    log_event(self._session_id, EVT_TRANSCRIPT_RECEIVED, {
                        "question_id": question_id,
                        "text": text,
                        "deepgram_latency_ms": latency_ms,
                    })

                    await self._on_transcript(text)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("STT receive loop error: %s", exc)
