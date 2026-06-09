"""WebSocket audio framing and write-back.

Handles the raw I/O protocol between the browser and the server.
Binary frames: PCM audio in / TTS audio out.
Text frames: JSON control messages in / transcript updates out.
"""
import asyncio
import json
import logging
from typing import Callable, Awaitable

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class WebSocketTransport:
    """Thin wrapper over a FastAPI WebSocket that enforces the frame protocol."""

    def __init__(
        self,
        websocket: WebSocket,
        on_audio: Callable[[bytes], Awaitable[None]],
        on_control: Callable[[dict], Awaitable[None]],
    ) -> None:
        self._ws = websocket
        self._on_audio = on_audio
        self._on_control = on_control
        self._closed = False

    async def send_audio(self, audio_bytes: bytes) -> None:
        """Send a TTS audio chunk to the browser."""
        if self._closed:
            return
        try:
            await self._ws.send_bytes(audio_bytes)
        except Exception as exc:
            logger.warning("send_audio failed: %s", exc)
            self._closed = True

    async def send_transcript(self, speaker: str, text: str) -> None:
        """Send a transcript update to the browser."""
        if self._closed:
            return
        try:
            await self._ws.send_text(json.dumps({
                "type": "transcript",
                "speaker": speaker,
                "text": text,
            }))
        except Exception as exc:
            logger.warning("send_transcript failed: %s", exc)
            self._closed = True

    async def receive_loop(self) -> None:
        """Pump incoming frames until disconnect."""
        try:
            while True:
                message = await self._ws.receive()
                if "bytes" in message and message["bytes"]:
                    await self._on_audio(message["bytes"])
                elif "text" in message and message["text"]:
                    try:
                        payload = json.loads(message["text"])
                    except json.JSONDecodeError:
                        logger.warning("Non-JSON text frame ignored")
                        continue
                    if isinstance(payload, dict) and payload.get("type") == "control":
                        await self._on_control(payload)
        except WebSocketDisconnect:
            self._closed = True
        except Exception as exc:
            logger.error("receive_loop error: %s", exc)
            self._closed = True
