# Project Architecture

## Two-System Design

The backend is split into two fully independent systems. They share no internal state and communicate only through events.

**System 1 — Voice Pipeline** handles audio I/O. It has no intelligence, no interview logic, no scoring, and no decision-making. Its only job is converting audio to text and text back to audio, reliably and fast.

**System 2 — Interview Orchestrator** is the brain. Given the current conversation state, it decides what happens next. All Gemini calls, scoring, follow-up logic, and interview strategy live here.

This split means:
- The voice pipeline can be tested without any LLM calls
- The orchestrator can be tested by replaying transcripts — no audio needed
- Providers (Deepgram, Cartesia, Gemini) can each be swapped independently
- Latency bottlenecks are traceable to one system, not a tangled call chain

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER BROWSER                             │
│  [Upload PDF] → [Start Interview] → [Live Transcript] → [PDF]  │
└─────────────────┬───────────────────────────────┬───────────────┘
                  │ HTTP (upload)                 │ WebSocket (audio)
                  ▼                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  SYSTEM 1 — VOICE PIPELINE           (no intelligence)          │
│                                                                 │
│   WebSocket → Silero VAD → Deepgram STT → transcript event      │
│                                               │                 │
│                                               ▼                 │
│   Cartesia TTS ← text response  ←────────────┤                 │
│                                               │                 │
└───────────────────────────────────────────────┼─────────────────┘
                                                │ transcript event
                                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  SYSTEM 2 — INTERVIEW ORCHESTRATOR   (all intelligence)         │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │ PDF Parser   │    │ Question     │    │  Interview       │  │
│  │ (pdfplumber) │───▶│ Generator    │───▶│  State Machine   │  │
│  │ + Gemini     │    │ (Gemini)     │    │  (Gemini)        │  │
│  └──────────────┘    └──────────────┘    └────────┬─────────┘  │
│                                                   │             │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Async Scoring  [transcript] → Gemini → ScoreResult      │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Report Generator  [scores] → Gemini → WeasyPrint PDF   │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Voice Pipeline Responsibilities

The voice pipeline does exactly four things and nothing else:

| Responsibility | Tool | What it produces |
|---|---|---|
| Speech-to-text | Deepgram Nova-3 | Final transcript string (~150ms latency) |
| Voice activity detection | Silero VAD | `vad_start` / `vad_end` events |
| Text-to-speech | Cartesia Sonic | Audio stream (~40ms TTFA) |
| Streaming transport | WebSocket + Pipecat | Audio chunks, interruption detection, buffering |

When a final transcript arrives, the pipeline emits a `transcript_received` event and waits. It does not call Gemini. It does not look at the question bank. It does not know what phase the interview is in.

---

## Interview Orchestrator Responsibilities

The orchestrator receives `transcript_received` events and decides what text to send back to the voice pipeline.

Its internal state per session:

| State field | What it tracks |
|---|---|
| `question_bank` | The 28 pre-generated questions for this session |
| `current_question_idx` | Which question is active |
| `follow_up_count` | How many follow-ups have been used on the current question (max 2) |
| `key_facts_mentioned` | Facts extracted from answers so far — injected into each Gemini call |
| `transcript_log` | Full conversation history |

Decision flow on each `transcript_received` event:

```
transcript received
  → update transcript_log and key_facts_mentioned
  → call Gemini with: current question + transcript + conversation state
  → Gemini returns: { action: "follow_up" | "probe" | "next_question" | "close", text: "..." }
  → emit text response → Voice Pipeline → Cartesia TTS
  → [async] fire scoring for the completed answer
  → log question_asked event
```

---

## Data Flow

```
PDF upload
  → pdfplumber extracts raw text
  → Gemini extracts structured JSON
  → [Pydantic] validates → ResumeData
  → Gemini generates question bank
  → [Pydantic] validates → QuestionBank → stored in SQLite

Voice session starts
  → Browser mic → WebSocket → Voice Pipeline
  → Silero VAD fires vad_start / vad_end events
  → Deepgram transcribes → transcript_received event
  → Orchestrator receives event → Gemini decision
  → text response → Voice Pipeline → Cartesia speaks
  → [async] answer → Gemini scoring → [Pydantic] validates → ScoreResult → SQLite

Session ends
  → Orchestrator triggers report
  → Gemini synthesizes all scores → [Pydantic] validates → ReportData
  → WeasyPrint renders PDF
  → User downloads report
```

---

## Pydantic Validation Layer

All LLM outputs are validated through Pydantic models before being used by any downstream layer. No raw LLM JSON is passed directly to the database, voice pipeline, or report renderer.

Models live in `backend/schemas/`. One file per domain.

| Model | File | Validated after |
|---|---|---|
| `ResumeData` | `schemas/resume.py` | Gemini extraction (Layer 1) |
| `QuestionBank` | `schemas/questions.py` | Gemini question generation (Layer 2) |
| `TranscriptEntry` | `schemas/session.py` | Each voice answer stored (Layer 3) |
| `ScoreResult` | `schemas/scoring.py` | Gemini per-answer scoring (Layer 4) |
| `ReportData` | `schemas/report.py` | Gemini report synthesis (Layer 5) |
| `UploadRequest` | `schemas/api.py` | FastAPI upload endpoint (API boundary) |
| `SessionResponse` | `schemas/api.py` | FastAPI session responses (API boundary) |

**Rule:** If a Pydantic model fails validation on an LLM response, log the raw output and raise — never silently coerce or skip fields. The LLM prompt needs fixing, not the validator.

---

## Event Logging

Every meaningful moment in the voice pipeline is written to an `events` table in SQLite. This is the primary tool for debugging latency spikes, weird pauses, duplicate questions, and out-of-order scoring.

### `events` table schema

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `session_id` | TEXT | Foreign key to sessions table |
| `event_type` | TEXT | One of the event types below |
| `ts` | REAL | Unix timestamp with millisecond precision |
| `payload` | TEXT | JSON — event-specific metadata |

### Event types

| Event | When it fires | Key payload fields |
|---|---|---|
| `vad_start` | Silero detects speech beginning | `question_id` |
| `vad_end` | Silero detects speech ending | `question_id`, `speech_duration_ms` |
| `transcript_received` | Deepgram returns final transcript | `question_id`, `text`, `deepgram_latency_ms` |
| `question_asked` | Agent begins speaking a question | `question_id`, `category`, `text` |
| `interruption` | User barge-in detected mid-TTS | `question_id`, `tts_elapsed_ms` |
| `tts_complete` | Cartesia finishes speaking | `question_id`, `ttfa_ms`, `total_duration_ms` |
| `scoring_complete` | Async scoring finishes for an answer | `question_id`, `scores`, `scoring_duration_ms` |

### What you can debug with this

- **Weird pauses** — gap between `vad_end` and `question_asked` timestamps reveals where time is lost (LLM decision, TTS queue, etc.)
- **Duplicate questions** — two `question_asked` events with the same `question_id` in one session
- **Latency spikes** — `deepgram_latency_ms` or `ttfa_ms` outliers per session
- **Scoring lag** — `scoring_complete` timestamp vs. next `question_asked` confirms scoring never blocks the voice loop
- **Interruption patterns** — frequency of `interruption` events flags prompts that are too long

### Where it lives

Event writes go through a single helper in `backend/db/events.py`. No layer writes directly to the `events` table — they call `log_event(session_id, event_type, payload)`. This keeps the table schema changes isolated to one file.

---

## File Structure

```
Interview-Agent/
├── backend/
│   ├── api/                  # FastAPI route handlers (upload, session, report endpoints)
│   ├── voice_pipeline/       # System 1 — audio I/O only (STT, VAD, TTS, WebSocket transport)
│   ├── orchestrator/         # System 2 — interview brain (state machine, Gemini calls, decisions)
│   ├── parser/               # Resume PDF extraction (pdfplumber + PyMuPDF fallback)
│   ├── question_gen/         # Question bank generation from ResumeData
│   ├── scoring/              # Async per-answer scoring
│   ├── report/               # Report synthesis and WeasyPrint PDF rendering
│   ├── db/                   # SQLite schema, query helpers, and event logger (events.py)
│   ├── prompts/              # Versioned LLM prompt files (v1.txt, v2.txt per prompt type)
│   ├── schemas/              # Pydantic models for all LLM outputs and API boundaries
│   └── templates/            # Jinja2 HTML templates for PDF report rendering
├── frontend/                 # React browser UI
│   └── src/
│       ├── components/       # Reusable UI pieces (transcript view, score bars, upload widget)
│       └── pages/            # Top-level pages (upload, interview, report)
├── uploads/                  # Temporary storage for incoming PDF resumes
├── reports/                  # Generated PDF interview reports
├── data/                     # SQLite database file (sessions, transcripts, scores, events)
├── DOCS/                     # Project documentation and planning
└── Interv/                   # Python 3.11 virtual environment (not committed)
```

## Where to add new folders

| Need | Add under |
|---|---|
| New API endpoint | `backend/api/` |
| Voice pipeline change (STT/VAD/TTS/transport) | `backend/voice_pipeline/` |
| Orchestrator logic (decisions, state, Gemini) | `backend/orchestrator/` |
| Resume parsing change | `backend/parser/` |
| Question generation change | `backend/question_gen/` |
| Scoring change | `backend/scoring/` |
| Report change | `backend/report/` |
| New prompt | `backend/prompts/` |
| New Pydantic model | `backend/schemas/` |
| New event type | `backend/db/events.py` |
| New UI component | `frontend/src/components/` |
| New page/route | `frontend/src/pages/` |
| Static assets (fonts, icons) | `frontend/src/assets/` ← create when needed |
| Tests | `tests/` at root ← create when needed |
