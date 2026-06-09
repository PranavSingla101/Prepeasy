# Feature Spec — Day 3: Voice Pipeline + Interview Orchestrator

**Goal:** Two independent systems that communicate only through events. The voice pipeline converts audio to text and text back to audio. The orchestrator holds all interview logic. Wire them together through the `transcript_received` event.

---

## Overview

Day 3 builds two things that must work independently before being wired together:

- **System 1 — Voice Pipeline** (`backend/voice_pipeline/`): Audio I/O only. No LLM calls, no interview logic. STT → event → receive text → TTS.
- **System 2 — Interview Orchestrator** (`backend/orchestrator/`): All intelligence. Receives transcript events, calls Gemini, manages interview state, emits text responses.
- **Event Logger** (`backend/db/events.py`): Single helper all layers call. Never write directly to the `events` table from a layer file.

**Alignment rule:** The voice pipeline must never import from `backend/orchestrator/`. The orchestrator must never import from `backend/voice_pipeline/`. They communicate through the shared event bus only. Breaking this boundary makes the systems untestable in isolation.

---

## 1. WebSocket Transport

**Concern:** Moving audio between the browser and the backend, and moving audio from TTS back to the browser.

### Connection

A single WebSocket connection per session carries everything: raw PCM audio in, TTS audio out, and control messages.

**Endpoint:** `ws://localhost:8000/ws/interview/{session_id}`

On connection open:
- Validate `session_id` exists in SQLite (has a `question_bank` row). Reject with `4404` if not found.
- Attach the session's `QuestionBank` to the active session state. Do not re-fetch from SQLite mid-session.
- Start the Pipecat pipeline for this session.

**Inbound frame format (browser → server):**
- Binary frames: raw PCM audio at 16kHz, 16-bit mono. No header. Pipecat receives these directly.
- Text frames: JSON control messages with shape `{ "type": "control", "action": "skip" | "repeat" | "end_session" }`.

**Outbound frame format (server → browser):**
- Binary frames: TTS audio (PCM or opus-encoded, matching what Pipecat outputs from Google TTS).
- Text frames: JSON transcript updates with shape `{ "type": "transcript", "speaker": "user" | "agent", "text": "..." }`.

**Alignment rule:** `session_id` in the WebSocket path must match the `session_id` used as the key in `question_banks` and `events` tables. These three must always be in sync. Never generate a new `session_id` after the question bank has been saved.

---

## 2. Voice Pipeline (`backend/voice_pipeline/`)

**Concern:** Reliable, fast audio I/O. No intelligence. Every decision deferred to the orchestrator via event.

### Files

| File | Responsibility |
|---|---|
| `backend/voice_pipeline/__init__.py` | Package init |
| `backend/voice_pipeline/pipeline.py` | Pipecat pipeline assembly and lifecycle |
| `backend/voice_pipeline/transport.py` | WebSocket audio framing and write-back |
| `backend/voice_pipeline/vad.py` | Silero VAD integration, event emission |
| `backend/voice_pipeline/stt.py` | Deepgram Nova-3 streaming STT integration |
| `backend/voice_pipeline/tts.py` | Google AI Studio TTS wrapper, interrupt handling |
| `backend/voice_pipeline/events.py` | Event bus — wires pipeline output to orchestrator input |

### VAD — `vad.py`

Runs Silero VAD locally. Receives PCM audio chunks from the WebSocket transport. Fires events when speech boundaries are detected.

**On speech start:**
- Emit `vad_start` event via `log_event(session_id, "vad_start", { "question_id": current_question_id })`
- Begin buffering audio for STT

**On speech end (silence > 800ms):**
- Emit `vad_end` event: `log_event(session_id, "vad_end", { "question_id": current_question_id, "speech_duration_ms": N })`
- Flush buffered audio to STT

**Alignment rule:** `current_question_id` in VAD events must match the `question_id` currently active in the orchestrator's `InterviewState`. The voice pipeline reads this from shared session state — the orchestrator writes it there whenever it advances to a new question.

### STT — `stt.py`

Streams audio to Deepgram Nova-3 over a persistent WebSocket connection (not REST). Uses Deepgram's streaming API with interim results suppressed — only `is_final: true` transcripts are used.

**On final transcript received from Deepgram:**
- Record `deepgram_latency_ms` = current timestamp minus `vad_end` timestamp
- Emit `transcript_received` event: `log_event(session_id, "transcript_received", { "question_id": current_question_id, "text": transcript_text, "deepgram_latency_ms": N })`
- Dispatch the transcript to the orchestrator's `handle_transcript(session_id, text)` function
- Do NOT call Gemini. Do NOT look at the question bank. Do NOT make any decision.

**Alignment rule:** The `text` field in the `transcript_received` payload and the text dispatched to `handle_transcript` must be identical strings — same source, no transformation.

### TTS — `tts.py`

Wraps Google AI Studio TTS (Gemini TTS API). Called by the voice pipeline after the orchestrator returns a text response.

**Function:** `speak(session_id: str, question_id: str, text: str) -> None`

Steps:
1. Record `speak_start_ts`
2. Call Google TTS API with `text`. Stream audio chunks back over WebSocket as they arrive.
3. On first audio chunk received: emit `tts_start` internally (used to compute `ttfa_ms`)
4. Track whether the user barges in mid-playback (VAD fires `vad_start` while TTS is streaming)
5. On barge-in: stop streaming TTS audio immediately, emit `interruption` event: `log_event(session_id, "interruption", { "question_id": question_id, "tts_elapsed_ms": N })`
6. On TTS stream complete without interruption: emit `tts_complete` event: `log_event(session_id, "tts_complete", { "question_id": question_id, "ttfa_ms": N, "total_duration_ms": N })`

**Alignment rule:** Barge-in must cancel only the current TTS stream, not the orchestrator state. The orchestrator proceeds normally — the interruption is a transport event, not a state transition.

### Pipeline Assembly — `pipeline.py`

Assembles the Pipecat pipeline in order: `WebSocket Transport → Silero VAD → Deepgram STT → Event Bus → Orchestrator → TTS → WebSocket Transport`.

**Startup sequence:**
1. Initialize Deepgram streaming connection
2. Initialize Silero VAD
3. Await first audio frame before doing anything else — do not call TTS until audio has been received
4. Trigger orchestrator to speak the first question: call `orchestrator.start_session(session_id)` which returns the first question text
5. Pass that text to `tts.speak()`, emit `question_asked` event

**Shutdown:** When orchestrator emits `session_complete` or the WebSocket closes, flush any pending TTS, close the Deepgram stream, write final events, and clean up session state.

---

## 3. Interview Orchestrator (`backend/orchestrator/`)

**Concern:** All intelligence. Receives transcripts, manages interview state, calls Gemini, decides what happens next.

### Files

| File | Responsibility |
|---|---|
| `backend/orchestrator/__init__.py` | Package init |
| `backend/orchestrator/state.py` | `InterviewState` dataclass |
| `backend/orchestrator/orchestrator.py` | `handle_transcript()` and `start_session()` functions |
| `backend/prompts/interviewer_v1.txt` | Interviewer system prompt |

### `InterviewState` — `state.py`

One instance per active session. Stored in memory (a dict keyed by `session_id`) for the duration of the session.

| Field | Type | What it tracks |
|---|---|---|
| `session_id` | `str` | Key for all DB and event writes |
| `question_bank` | `QuestionBank` | All 28 questions — loaded once at session start, never re-fetched |
| `current_question_idx` | `int` | Index into `question_bank.questions`. Starts at 0. |
| `follow_up_count` | `int` | Follow-ups used on the current question. Resets to 0 on each new question. Max 2. |
| `key_facts_mentioned` | `list[str]` | Facts extracted from all answers so far. Injected into each Gemini call. Grows across the session. |
| `transcript_log` | `list[TranscriptEntry]` | Full conversation history in order. Each entry: `{ "speaker": "agent" | "user", "text": "...", "question_id": "..." }` |
| `silence_streak` | `int` | Consecutive seconds of no VAD activity on current question. Reset on `vad_start`. Triggers edge case at 8. |
| `session_active` | `bool` | False after orchestrator emits `session_complete`. Rejects any new transcripts. |

**Alignment rule:** `current_question_idx` determines `current_question_id` (used in all VAD, STT, and TTS events). Whenever `current_question_idx` advances, the voice pipeline's `current_question_id` must be updated in the same operation — not deferred.

### `start_session()` — `orchestrator.py`

Called once when the WebSocket connects and the pipeline is ready.

**State mutation:**
- Loads `QuestionBank` from SQLite via `get_question_bank(session_id)`
- Creates a fresh `InterviewState` with `current_question_idx = 0`, `follow_up_count = 0`, empty `transcript_log` and `key_facts_mentioned`
- Stores `InterviewState` in the in-memory session dict

**API call:** None. No Gemini call on start.

**Side effect:**
- Returns the text of `question_bank.questions[0].text` to the caller (voice pipeline), which passes it to TTS
- Emits `question_asked` event: `log_event(session_id, "question_asked", { "question_id": "behavioral_01", "category": "behavioral", "text": "..." })`

### `handle_transcript()` — `orchestrator.py`

The core decision function. Called every time Deepgram returns a final transcript.

**Signature:** `handle_transcript(session_id: str, text: str) -> str`

Returns the text the voice pipeline should speak next.

**State mutations (in order):**

1. Append to `transcript_log`: `{ "speaker": "user", "text": text, "question_id": current_question_id }`
2. Extract any key facts from the answer (names, numbers, outcomes mentioned) and append to `key_facts_mentioned`
3. Reset `silence_streak` to 0

**API call — Gemini decision:**

- Load prompt from `backend/prompts/interviewer_v1.txt`
- Inject into prompt: current question text, current question's `follow_up_vague` and `follow_up_strong`, full `transcript_log`, `key_facts_mentioned`, `follow_up_count`, `current_question_idx`, total question count
- Call Gemini 2.5 Flash with `response_mime_type="application/json"`
- Expected response shape: `{ "action": "follow_up" | "probe" | "next_question" | "close", "text": "..." }`
- Validate with Pydantic `OrchestratorDecision` model (defined in `backend/schemas/session.py`)

**Decision routing:**

| Gemini action | Condition guard | State mutation | Side effect |
|---|---|---|---|
| `"follow_up"` | `follow_up_count < 2` | Increment `follow_up_count` | Speak `decision.text` |
| `"follow_up"` | `follow_up_count >= 2` | Override to `next_question` | Advance question (see below) |
| `"probe"` | `follow_up_count < 2` | Increment `follow_up_count` | Speak `decision.text` |
| `"probe"` | `follow_up_count >= 2` | Override to `next_question` | Advance question |
| `"next_question"` | `current_question_idx < len(questions) - 1` | Increment `current_question_idx`, reset `follow_up_count` to 0 | Speak `decision.text` + next question text, fire scoring |
| `"next_question"` | `current_question_idx == len(questions) - 1` | Set `session_active = False` | Speak closing statement, emit `session_complete` |
| `"close"` | Any | Set `session_active = False` | Speak `decision.text`, emit `session_complete` |

**After Gemini response, before returning text:**
- Append agent response to `transcript_log`: `{ "speaker": "agent", "text": response_text, "question_id": current_question_id }`
- If action advanced to next question: emit `question_asked` event for the new question
- If action advanced to next question: fire async scoring for the completed answer (see section 4)
- Return `response_text` to voice pipeline

**Alignment rule:** If Gemini returns an action of `"follow_up"` or `"probe"` but `follow_up_count` is already 2, the orchestrator must override to `next_question` locally — do not re-call Gemini. The guard is in the orchestrator, not the LLM.

### Edge Cases — `orchestrator.py`

These are handled in `handle_transcript` before the Gemini call:

| Trigger | Detection | Response |
|---|---|---|
| Repeat request | Transcript contains "repeat" or "say that again" (case-insensitive substring match) | Return the `text` field of `question_bank.questions[current_question_idx]` directly. Do not call Gemini. Do not count as a follow-up. |
| Skip request | Transcript contains "skip" or "next question" | Advance to next question immediately. Do not call Gemini. Emit `question_asked` for new question. Fire scoring with a `"skipped": true` flag in payload. |
| One-word answer | `len(text.strip().split()) <= 2` | Force Gemini decision to use `follow_up_vague` — set it as the only option in the prompt context. Do not allow `next_question`. |
| User silence (8+ seconds) | `silence_streak >= 8` (incremented by a periodic timer, not by transcript events) | Speak a prompt: "Take your time, or say 'skip' to move on." Do not call Gemini. Do not count against `follow_up_count`. |

### Interviewer Prompt — `backend/prompts/interviewer_v1.txt`

The system prompt must communicate:

- Role: You are a professional interviewer. You already have the question bank — you are not generating new questions. You are deciding how to respond to the user's last answer.
- Context injected per call: current question text, prepared follow-ups (vague and strong), conversation history, key facts the user has mentioned, how many follow-ups have been used
- Output schema: `{ "action": "follow_up" | "probe" | "next_question" | "close", "text": "..." }`
- Action definitions: `follow_up` = use the prepared `follow_up_vague`, `probe` = use the prepared `follow_up_strong`, `next_question` = transition to next question, `close` = end session
- Tone rules: conversational, not stiff. Acknowledge what was said before asking the next question. Never say "Great answer!" or generic affirmations. Do not repeat back the user's answer verbatim.
- Hard constraint: `text` field must be spoken language only — no markdown, no bullet points, no headers.

**Alignment rule:** The prompt must include the exact follow-up texts from the question bank (`follow_up_vague`, `follow_up_strong`) so Gemini returns modified versions of these, not free-form responses. This ensures follow-up quality is anchored to the pre-generated bank.

---

## 4. Async Scoring Trigger

**Concern:** Per-answer scoring must fire without blocking the voice loop.

When the orchestrator advances to a new question (or closes the session), it fires background scoring for the completed answer.

**Where it fires:** Inside `handle_transcript()` after the decision to advance, before returning the response text.

**What it dispatches:**
- `session_id`
- `question_id` of the completed question
- Full transcript for that question only (filtered from `transcript_log` by `question_id`)
- The question text itself

**How it fires:** `asyncio.create_task(score_answer(session_id, question_id, question_text, answer_transcript))` — fire and forget. The voice loop does not await this.

**Side effect:** On scoring complete, `backend/scoring/` writes the `ScoreResult` to SQLite and emits `scoring_complete` event: `log_event(session_id, "scoring_complete", { "question_id": question_id, "scores": {...}, "scoring_duration_ms": N })`.

**Alignment rule:** The `question_id` dispatched to scoring must be the ID of the question that just finished — `question_bank.questions[current_question_idx - 1].id` after the index has been incremented. Never dispatch the new (active) question's ID.

---

## 5. Event Logger (`backend/db/events.py`)

**Concern:** Central write point for all session events. One function. Never bypass it.

### `events` Table

Created on first write if it does not exist. Schema:

| Column | Type | Notes |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY` | Auto-increment |
| `session_id` | `TEXT` | Foreign key to `sessions` |
| `event_type` | `TEXT` | One of the canonical types below |
| `ts` | `REAL` | `time.time()` — Unix timestamp with millisecond precision |
| `payload` | `TEXT` | JSON string — event-specific fields |

### `log_event()` Function

**Signature:** `log_event(session_id: str, event_type: str, payload: dict) -> None`

Steps:
1. Serialize `payload` to JSON string
2. Insert row into `events` table with current timestamp
3. On SQLite write failure: log the error but do not raise — event writes must never crash the voice pipeline

**Alignment rule:** Every event write across the codebase must go through `log_event`. No layer imports `sqlite3` and writes to `events` directly.

### Canonical Event Types

| Event | When | Required payload fields |
|---|---|---|
| `vad_start` | Silero detects speech beginning | `question_id` |
| `vad_end` | Silero detects speech ending | `question_id`, `speech_duration_ms` |
| `transcript_received` | Deepgram returns final transcript | `question_id`, `text`, `deepgram_latency_ms` |
| `question_asked` | Agent begins speaking a question | `question_id`, `category`, `text` |
| `interruption` | User barges in mid-TTS | `question_id`, `tts_elapsed_ms` |
| `tts_complete` | TTS finishes speaking without interruption | `question_id`, `ttfa_ms`, `total_duration_ms` |
| `scoring_complete` | Async scoring finishes for an answer | `question_id`, `scores`, `scoring_duration_ms` |

**Alignment rule:** `event_type` must be one of these strings exactly. Typos in event type strings produce silent gaps in the event log that are very hard to debug. Define these as string constants in `events.py` and import from there — never write the string inline in a call site.

---

## 6. Pydantic Models (`backend/schemas/session.py`)

New models needed for Day 3:

**`TranscriptEntry`**
- `speaker: Literal["user", "agent"]`
- `text: str`
- `question_id: str`
- `ts: float` — Unix timestamp

**`OrchestratorDecision`**
- `action: Literal["follow_up", "probe", "next_question", "close"]`
- `text: str` — the spoken response

**Validation rules:**
- `OrchestratorDecision.text` must be non-empty. If Gemini returns an empty string, raise — do not speak silence.
- If validation fails on `OrchestratorDecision`, log the raw Gemini output and raise. Do not attempt to recover with a fallback text.

---

## 7. FastAPI WebSocket Endpoint (`backend/api/`)

**Concern:** Expose the voice pipeline over WebSocket. Wire session lifecycle to connect/disconnect events.

**Route:** `ws://localhost:8000/ws/interview/{session_id}`

On connect:
- Validate `session_id` has a `question_bank` row
- Call `orchestrator.start_session(session_id)` → get first question text
- Pass text to `pipeline.start(session_id, websocket, first_question_text)`

On binary frame received:
- Forward raw audio to Pipecat pipeline

On text frame received:
- Parse as JSON, dispatch to control handler (skip / repeat / end_session)

On disconnect:
- Flush TTS if mid-stream
- Close Deepgram connection
- Remove `InterviewState` from in-memory session dict
- Log a `session_end` event (add this to canonical types in `events.py`)

---

## 8. Silence Timer

**Concern:** Detect when the user has gone silent for 8+ seconds.

Run a periodic `asyncio` task per session (fires every 1 second). On each tick: if `silence_streak >= 8` and no active TTS playback, call `orchestrator.handle_silence(session_id)` which returns the nudge text. Pass to TTS. Reset `silence_streak` to 0 after speaking the nudge.

`silence_streak` increments each second there is no `vad_start`. It resets to 0 on any `vad_start` event.

**Alignment rule:** The silence timer must not fire while TTS is playing. Check `pipeline.is_speaking` flag before emitting a nudge. A nudge mid-TTS would overlap audio.

---

## Check When Done

Observable behaviors that confirm Day 3 is complete:

- [ ] **End-to-end voice session:** Connect from browser, speak an answer, hear the agent respond. Five questions asked without manual intervention.
- [ ] **Pipeline isolation:** Run orchestrator by replaying a hardcoded transcript list (no audio, no Deepgram) — verify correct `action` sequence without any voice pipeline code loaded.
- [ ] **Transcript storage:** After a 5-question session, query `events` table — every question has a `transcript_received` row with the spoken text.
- [ ] **Event completeness:** For each question: `question_asked` → `vad_start` → `vad_end` → `transcript_received` → next `question_asked`. All rows present, timestamps in order.
- [ ] **Follow-up cap:** Give a one-word answer three times in a row for one question — confirm the agent moves on after 2 follow-ups, not 3.
- [ ] **Repeat edge case:** Say "can you repeat that?" — confirm the same question is spoken again with no Gemini call and `follow_up_count` unchanged.
- [ ] **Barge-in:** Interrupt the agent mid-sentence — confirm TTS stops, `interruption` event is logged, STT picks up the user's speech correctly.
- [ ] **Silence nudge:** Stay silent for 10 seconds — confirm agent speaks the nudge text, `silence_streak` resets.
- [ ] **Scoring non-blocking:** `scoring_complete` event timestamp is always after the next `question_asked` timestamp — scoring never holds up the voice loop.
- [ ] **No cross-boundary imports:** `grep -r "from backend.orchestrator" backend/voice_pipeline/` returns nothing. `grep -r "from backend.voice_pipeline" backend/orchestrator/` returns nothing.
- [ ] **Pydantic validation:** Force a bad Gemini response (mock the call) — confirm the pipeline raises, logs raw output, and does not speak garbage or silence.
