# Progress Tracker

Update this file after every meaningful implementation change.

## Current Phase

- In Progress

## Current Goal

- Day 5 complete — Silent per-answer scoring implemented; moving to Day 6 report synthesis

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
- `backend/schemas/session.py` — added `key_facts: list[str] = []` to `OrchestratorDecision`; Gemini now returns extracted facts alongside action and text
- `backend/prompts/interviewer_v1.txt` — updated to v2 format: includes question ID/category/source_ref context; requests `key_facts` array in JSON output; added tone rule forbidding "vague", "probe", "rubric", "score", "follow-up count" in spoken text
- `backend/db/events.py` — added `EVT_DECISION_MADE = "decision_made"` constant for adaptive decision audit trail
- `backend/orchestrator/orchestrator.py` — Day 4 adaptive logic: (1) key facts merged into `state.key_facts_mentioned` from each Gemini response; (2) raw model action (`model_action`) stored before follow-up cap guard so override is distinguishable in logs; (3) `decision_made` event logged per turn with `model_action`, `decision_action`, `follow_up_count`, `question_id`; (4) `_build_prompt` injects `question_id`, `question_category`, `question_source_ref`
- `backend/schemas/scoring.py` — `ScoreResult` Pydantic model; four 1–10 dimensions (`relevance`, `specificity`, `structure`, `communication`); `overall` computed by model validator (arithmetic mean, 1 decimal) — not returned by Gemini; skipped validation enforces all-null; float→int coercion; non-empty string validation on `strongest_moment`/`weakest_moment`
- `backend/prompts/scoring_v1.txt` — Gemini scoring prompt; STAR rubric for `specificity`; forbids generic observations for moment fields; forbids rubric language in `suggested_rewrite`; handles skipped flag
- `backend/scoring/__init__.py` — package init
- `backend/scoring/scorer.py` — `score_answer_async`; filters transcript to user turns only; calls Gemini 2.5 Flash via `run_in_executor`; validates through `ScoreResult`; persists via `save_score`; emits `scoring_complete` event; full error isolation — no exception escapes
- `backend/db/session.py` — added `_ensure_scores_table`, `save_score`, `get_scores`; `scores` table with `UNIQUE(session_id, question_id)` constraint; lazy table init pattern
- `backend/orchestrator/orchestrator.py` — replaced `_score_answer` placeholder with delegation to `score_answer_async`; threaded `question_category` through both `asyncio.create_task` call sites in `_advance_question`; removed unused `EVT_SCORING_COMPLETE` import

## In Progress

- DEEPGRAM_API_KEY needs to be added to .env (GEMINI_API_KEY already set)
- Live end-to-end test: connect browser mic, verify session with adaptive follow-up + scoring behavior

## Next Up

- Add `DEEPGRAM_API_KEY` to `.env`
- Run server: `Interv\Scripts\uvicorn backend.main:app --reload --port 8000`
- Verify Day 5 checklist items in `DOCS/Feature-specs/05-silent-per-answer-scoring.md`
- Day 6 — Report synthesis (`backend/report/synthesizer.py`, `backend/schemas/report.py`, `backend/prompts/report_v1.txt`)

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
- **Day 4 adaptive follow-up spec** created at `DOCS/Feature-specs/04-adaptive-follow-up-logic.md`; it treats the next work as orchestration refinement before real scoring
- **Day 5 scoring spec** created at `DOCS/Feature-specs/05-silent-per-answer-scoring.md`
- **ScoreResult.overall** is computed by the Pydantic model validator, not returned by Gemini — prevents prompt drift affecting aggregates
- **Scoring error isolation**: `score_answer_async` wraps entire body in try/except; a scoring failure logs and returns silently, never crashing the voice session
- **Scores table UNIQUE constraint** on `(session_id, question_id)` — duplicate insert raises `IntegrityError`, caught by scorer
- **question_category threaded through orchestrator**: `_score_answer` now accepts and forwards `question_category` to `score_answer_async`; `question_id` in scores table matches `question_id` in `question_asked` events — the join key for Day 6 reporting
- **Key facts extraction**: `OrchestratorDecision` extended with `key_facts: list[str]`; Gemini returns 0–5 concise facts per answer; orchestrator deduplicates and accumulates into `state.key_facts_mentioned`; injected into every subsequent Gemini call for context continuity
- **Decision audit trail**: `EVT_DECISION_MADE` event logs `model_action` (raw Gemini output) and `decision_action` (after follow-up cap guard override) so overrides are distinguishable in SQLite events table
- **Prompt context completeness**: `_build_prompt` now injects `question_id`, `question_category`, `question_source_ref` per Day 4 spec requirement

## Session Notes

- Virtual env: `Interv/` — activate with `Interv\Scripts\activate`
- All required packages installed: pdfplumber, PyMuPDF, google-genai, python-dotenv, pydantic, sqlite3 (stdlib), pipecat-ai, deepgram-sdk, fastapi, uvicorn, websockets
- Run parser: `python -m backend.parse_resume <path/to/resume.pdf>` from project root
- Run question gen: `python -m backend.generate_questions <resume_id>`
- Run server: `Interv\Scripts\uvicorn backend.main:app --reload --port 8000`
- `.env` must contain: `GEMINI_API_KEY=...` and `DEEPGRAM_API_KEY=...`
