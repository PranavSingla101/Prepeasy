# Progress Tracker

Update this file after every meaningful implementation change.

## Current Phase

- In Progress

## Current Goal

- Day 3 — Voice Pipeline + Interview Orchestrator: WebSocket → STT → Orchestrator → TTS

## Completed

- `backend/parser/extractor.py` — PDF text extraction (pdfplumber primary, PyMuPDF fallback); hardened for password-protected and corrupt PDFs
- `backend/parser/prompts/extraction_v1.txt` — original prompt location (kept for reference)
- `backend/prompts/extraction_v1.txt` — Gemini extraction prompt at architecture-correct location
- `backend/parser/structured.py` — Calls Gemini 2.5 Flash; validates output through `ResumeData` Pydantic model; returns `ResumeData`
- `backend/schemas/__init__.py` — schemas package
- `backend/schemas/resume.py` — `ResumeData` Pydantic model (`Contact`, `Skills`, `Education`, `ExperienceEntry`, `ResumeData`)
- `backend/db/session.py` — SQLite init + `save_resume()` + `get_resume()`, DB at `data/interviews.db`
- `backend/parse_resume.py` — CLI entry-point wiring extraction → Pydantic validation → SQLite; prints `resume_id`, `gap_analysis`, and full JSON
- `.env` — template created (`GEMINI_API_KEY` placeholder)
- `backend/schemas/questions.py` — `Question` and `QuestionBank` Pydantic models; validators enforce exactly 28 questions, all categories present, gap_probing source_ref non-empty
- `backend/prompts/questions_v1.txt` — Gemini prompt with category-specific instructions, forbidden question list, and readable resume injection format
- `backend/question_gen/__init__.py` — package init
- `backend/question_gen/generator.py` — `generate_question_bank(resume, session_id) -> QuestionBank`; injects resume as readable blocks, calls Gemini 2.5 Flash with JSON mime type
- `backend/db/session.py` — added `save_question_bank()` and `get_question_bank()`; creates `question_banks` table; raises on duplicate session_id
- `backend/generate_questions.py` — CLI entry point; fetches ResumeData by resume_id, generates bank, saves to SQLite, prints category counts and all 28 questions
- `backend/db/events.py` — `log_event()` with canonical event-type constants; events table auto-created on first write; write failures are logged but never raised
- `backend/schemas/session.py` — `TranscriptEntry` and `OrchestratorDecision` Pydantic models; `OrchestratorDecision.text` validator rejects empty strings
- `backend/orchestrator/__init__.py` — package init
- `backend/orchestrator/state.py` — `InterviewState` dataclass (session_id, question_bank, current_question_idx, follow_up_count, key_facts_mentioned, transcript_log, silence_streak, session_active)
- `backend/orchestrator/orchestrator.py` — `start_session()`, `handle_transcript()`, `handle_silence()`, `get_state()`, `end_session()`; repeat/skip/one-word edge cases; follow-up cap guard; async Gemini calls; non-blocking `_score_answer()` task
- `backend/prompts/interviewer_v1.txt` — Interviewer system prompt with injected context fields and JSON output schema
- `backend/voice_pipeline/__init__.py` — package init
- `backend/voice_pipeline/events.py` — Event bus (sole authorised crossing point); exposes dispatch_transcript, dispatch_silence, and state-read helpers; pipeline.py never imports orchestrator directly
- `backend/voice_pipeline/vad.py` — `VADProcessor` using Pipecat `SileroVADAnalyzer` (800ms stop_secs); fires `vad_start`/`vad_end` events via log_event; calls STT begin_speech/end_speech callbacks
- `backend/voice_pipeline/stt.py` — `STTSession` using Deepgram SDK v7 async WebSocket; only processes `is_final=True` transcripts; emits `transcript_received` event
- `backend/voice_pipeline/tts.py` — `TTSSession` wrapping Google GenAI streaming TTS (gemini-2.5-flash-preview-tts); barge-in cancels current stream and emits `interruption` event; emits `tts_complete` on clean finish
- `backend/voice_pipeline/transport.py` — `WebSocketTransport` for binary PCM frames (in/out) and JSON text frames (control/transcript)
- `backend/voice_pipeline/pipeline.py` — `InterviewPipeline` assembles all components; silence timer (1s tick, 8s threshold); first-audio gate before TTS; clean shutdown on disconnect
- `backend/api/__init__.py` — package init
- `backend/api/interview.py` — FastAPI router with `ws://localhost:8000/ws/interview/{session_id}`; 4404 on missing session; delegates lifecycle to InterviewPipeline
- `backend/main.py` — FastAPI app with health check; loads .env; mounts interview router

## In Progress

- DEEPGRAM_API_KEY needs to be added to .env (GEMINI_API_KEY already set)
- Live end-to-end test: connect browser mic, verify 5-question session with scoring events

## Next Up

- Add `DEEPGRAM_API_KEY` to `.env`
- Run server: `Interv\Scripts\uvicorn backend.main:app --reload --port 8000`
- Verify all checklist items in `DOCS/Feature-specs/03-Voice-pipeline.md`
- Day 4 — Scoring module (`backend/scoring/`) + report generator

## Open Questions

- None at this time

## Architecture Decisions

- **Gemini 2.5 Flash** used as LLM (not Claude) — specified in `DOCS/Tech-stack.md`
- **SQLite DB** stored at `data/interviews.db` (project root), gitignored
- `response_mime_type="application/json"` used in Gemini call to enforce JSON output natively
- Prompt template lives at `backend/prompts/extraction_v1.txt` — never hardcoded in Python
- `ResumeData.model_validate()` used after JSON parse — if validation fails, fix the prompt, not the schema
- `duration_months` has a `coerce_duration` validator to handle LLM returning strings instead of ints
- Question bank prompt injects resume as human-readable blocks (not raw JSON) — more reliable LLM anchoring
- `gap_analysis` items are numbered in the prompt so gap_probing `source_ref` values are verifiable (`gap_1`, `gap_2`, ...)
- `session_id` is `{resume_id}_{unix_timestamp}` for CLI; becomes a UUID when the FastAPI upload endpoint is added (Day 4)
- `QuestionBank` validator enforces exactly 28 questions and all 5 categories present — hard fail, no coercion
- Temperature set to 0.7 for question generation (vs 0.0 for extraction) — diversity in question phrasing is desirable
- **Event bus pattern**: `backend/voice_pipeline/events.py` is the only file allowed to import from `backend.orchestrator`; all other voice_pipeline files stay isolated
- **SileroVADAnalyzer** used directly from Pipecat (not the full Pipecat pipeline); stop_secs=0.8 (800ms per spec)
- **Deepgram SDK v7** (`AsyncDeepgramClient`) used for streaming STT; only `is_final=True` results processed
- **Google GenAI TTS** (`gemini-2.5-flash-preview-tts`) for TTS; streaming via `generate_content_stream`
- **Silence timer** fires every 1s asyncio task; skipped while TTS is playing; resets on vad_start
- **Scoring placeholder** in orchestrator — real scoring module goes in `backend/scoring/` (Day 4)

## Session Notes

- Virtual env: `Interv/` — activate with `Interv\Scripts\activate`
- All required packages installed: pdfplumber, PyMuPDF, google-genai, python-dotenv, pydantic, sqlite3 (stdlib), pipecat-ai, deepgram-sdk, fastapi, uvicorn, websockets
- Run parser: `python -m backend.parse_resume <path/to/resume.pdf>` from project root
- Run question gen: `python -m backend.generate_questions <resume_id>`
- Run server: `Interv\Scripts\uvicorn backend.main:app --reload --port 8000`
- `.env` must contain: `GEMINI_API_KEY=...` and `DEEPGRAM_API_KEY=...`
