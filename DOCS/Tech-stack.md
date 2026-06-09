# Tech Stack

## Voice Pipeline

| Tool | Role | Why |
|---|---|---|
| **Pipecat** | Pipeline orchestration (STT → LLM → TTS) | Purpose-built for real-time voice agents; handles turn-taking and barge-in out of the box |
| **Deepgram Nova-3** | Streaming speech-to-text | ~150ms P50 latency — fast enough to feel natural in conversation |
| **Silero VAD** | Voice activity detection | Runs locally on CPU, no API cost, reliable silence/speech boundary detection |
| **Google AI Studio TTS** | Text-to-speech | Native to the Gemini ecosystem; no additional API key — same `GEMINI_API_KEY` used for LLM calls |

## LLM

| Tool | Role | Why |
|---|---|---|
| **Gemini 2.5 Flash (Google)** | Resume extraction, question generation, scoring, report synthesis | Fast, cost-efficient, and strong structured JSON output — well-suited for high-frequency scoring calls |

## Resume Parsing

| Tool | Role | Why |
|---|---|---|
| **pdfplumber** | PDF text extraction (primary) | Handles complex multi-column layouts better than most open-source alternatives |
| **PyMuPDF** | PDF text extraction (fallback) | Covers scanned or image-heavy PDFs that pdfplumber fails on |

## Storage

| Tool | Role | Why |
|---|---|---|
| **SQLite** | Sessions, transcripts, scores | Zero setup, built into Python, sufficient for single-user or demo-scale data |

## Report Generation

| Tool | Role | Why |
|---|---|---|
| **WeasyPrint** | HTML + CSS → PDF | Lets you design the report in standard HTML/CSS — no proprietary PDF library to learn |
| **Jinja2** | HTML templating | Standard Python templating; pairs cleanly with WeasyPrint |

## Backend

| Tool | Role | Why |
|---|---|---|
| **FastAPI** | REST API + WebSocket server | Native async support for the voice WebSocket loop and background scoring tasks |
| **Uvicorn** | ASGI server | Required by FastAPI; handles concurrent WebSocket connections efficiently |

## Frontend

| Tool | Role | Why |
|---|---|---|
| **React** | Browser UI | Component model suits the live transcript + upload + report preview flow |
