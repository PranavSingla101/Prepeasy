# Interview Agent — Build Roadmap

---

## Day 1 — Resume Parser

**Goal:** PDF in → validated structured JSON out (with gap analysis), stored in SQLite.

- Write PDF extraction in `backend/parser/extractor.py` (pdfplumber primary, PyMuPDF fallback)
- Write Gemini extraction prompt in `backend/prompts/extraction_v1.txt`
- Write extraction caller in `backend/parser/structured.py`
- Define `ResumeData` Pydantic model in `backend/schemas/resume.py` — validate Gemini output before anything touches it
- Set up SQLite in `backend/db/session.py` — `resumes` table
- Wire CLI entry point `backend/parse_resume.py`
- Test on 3–5 real resumes of varying formats

**Verify:**
- Upload any PDF → get valid JSON in under 10 seconds
- `gap_analysis` array is populated with real observations
- `has_metrics` and `vague_claims` fields reflect the actual resume content
- Pydantic validation passes — if it fails, fix the prompt, not the schema

---

## Day 2 — Question Bank Generator

**Goal:** `ResumeData` → 28 personalized questions, validated and stored in SQLite.

- Write question generation prompt in `backend/prompts/questions_v1.txt`
- Write generator in `backend/question_gen/generator.py`
- Define `Question` and `QuestionBank` Pydantic models in `backend/schemas/questions.py`
- Store validated question bank in SQLite keyed by session ID
- Test on 3 resume types: junior dev, mid-level engineer, PM

**Verify:**
- Each behavioral question references a specific resume bullet
- Each gap-probing question targets something from `gap_analysis`
- 28 questions generated in under 15 seconds
- Manually read the output — every question should feel tailored, not generic
- `QuestionBank` Pydantic validation passes cleanly

---

## Day 3 — Voice Pipeline + Orchestrator (no scoring yet)

**Goal:** Build both systems independently, wire them together through the transcript event. Agent speaks a question, listens, stores the transcript.

### System 1 — Voice Pipeline (`backend/voice_pipeline/`)

- Set up Pipecat with Deepgram STT, Silero VAD, Cartesia TTS
- Build the pipeline: WebSocket audio → VAD → STT → emit `transcript_received` event
- Handle transport: audio chunks, interruption detection, buffering
- The pipeline never calls Gemini — it emits events and receives text back, nothing else

### System 2 — Interview Orchestrator (`backend/orchestrator/`)

- Define `InterviewState` with `question_bank`, `current_question_idx`, `follow_up_count`, `key_facts_mentioned`, `transcript_log`
- Write orchestrator decision function: receives `transcript_received` → calls Gemini → returns text response
- Write interviewer system prompt in `backend/prompts/interviewer_v1.txt`
- Handle basic edge cases: user asks to repeat, user goes silent 8+ seconds, user gives a 1-word answer

### Event Logging (`backend/db/events.py`)

- Create `events` table in SQLite
- Implement `log_event(session_id, event_type, payload)` helper
- Wire `vad_start`, `vad_end`, `transcript_received`, `question_asked`, `tts_complete`, `interruption` events

**Verify:**
- Complete a 5-minute voice session, 5 questions asked end-to-end
- Transitions between questions sound natural
- Transcripts are stored per answer
- `events` table has a row for every `vad_start`, `transcript_received`, and `question_asked`
- Voice pipeline test passes without any Gemini calls (replay a transcript directly to orchestrator)

---

## Day 4 — Adaptive Follow-up Logic

**Goal:** Orchestrator decides whether to follow up, probe deeper, or move on — not just read the next question.

- Update orchestrator decision logic: Gemini returns `{ action: "follow_up" | "probe" | "next_question" | "close", text: "..." }`
- Enforce `follow_up_count` max 2 per question in `InterviewState`
- Wire `follow_up_if_vague` when answer is too short or lacks specifics
- Wire `follow_up_if_good` when answer is strong — probe deeper
- Update `key_facts_mentioned` extraction after each answer

**Verify:**
- Give a vague answer → orchestrator uses `follow_up_if_vague`
- Give a strong answer → orchestrator probes with `follow_up_if_good`
- Give a complete answer → orchestrator moves on gracefully
- Run a 10-question session — at least 3 organic follow-ups
- Test by replaying transcripts through the orchestrator alone (no audio required)

---

## Day 5 — Silent Per-Answer Scoring

**Goal:** Every answer is scored in the background without adding any latency to the voice conversation.

- Write scoring prompt in `backend/prompts/scoring_v1.txt`
- Implement `score_answer_async` in `backend/scoring/scorer.py` — non-blocking, fires after each answer
- Define `ScoreResult` Pydantic model in `backend/schemas/scoring.py`
- Store validated scores in SQLite: `(session_id, question_id, scores_json, timestamp)`
- Wire `scoring_complete` event log on completion
- Capture `strongest_moment`, `weakest_moment`, `suggested_rewrite` per answer

**Verify:**
- Run a full 20-minute session
- After session ends, query SQLite — score row exists for every answer
- Check `events` table: `scoring_complete` timestamp never precedes the next `question_asked` — confirms scoring is non-blocking
- `ScoreResult` Pydantic validation passes for all answers

---

## Day 6 — Report Synthesis

**Goal:** All per-answer `ScoreResult` records → a validated `ReportData` object ready for rendering.

- Write report synthesis prompt in `backend/prompts/report_v1.txt`
- Implement synthesis in `backend/report/synthesizer.py`
- Define `ReportData` Pydantic model in `backend/schemas/report.py`
- Test on mock score data first before using real session data
- Ensure `per_question_feedback` contains exact transcript quotes
- Ensure `action_items` are specific — reference something the candidate actually said

**Verify:**
- `overall_score` is a reasonable reflection of session quality
- Every action item references something specific said during the interview — not "be more specific" generically
- `ReportData` Pydantic validation passes
- Run synthesis on real Day 5 session data

---

## Day 7 — PDF Report Generation

**Goal:** `ReportData` → a professional, downloadable PDF.

- Design `report_template.html` in `backend/templates/` with CSS: score bars, quote blocks, color-coded categories (red/amber/green)
- Implement renderer in `backend/report/renderer.py` — Jinja2 → WeasyPrint → PDF
- Add PDF download endpoint to `backend/api/`
- Test rendering on both mobile and desktop

**Verify:**
- Full end-to-end flow works: upload resume → voice interview → download PDF
- PDF looks professional enough to screenshot and share
- Quote blocks display exact transcript text correctly

---

## Day 8 — Session History & Score Trends

**Goal:** Users can run multiple interviews and see improvement over time.

- Add sessions list endpoint in `backend/api/` returning last N interviews with date and overall score
- Add `SessionResponse` Pydantic model in `backend/schemas/api.py`
- Add score trend display to UI or include in PDF
- Add resume version tracking — new upload creates a new `resume_id`

**Verify:**
- Run 3 sessions with the same resume
- Score trend data is accurate per category
- Uploading a new resume starts a fresh session lineage

---

## Day 9 — Job Description Targeting + UI Polish

**Goal:** Support targeting a specific role; make the UI demo-ready.

- Add "Target Job Description" text input on the upload page
- Adjust question generation prompt and `QuestionBank` schema to handle optional JD context
- Polish UI in `frontend/src/`: drag-and-drop upload, live transcript with speaker labels, session timer, report preview card
- Test mobile layout

**Verify:**
- Paste a real JD → question bank includes role-specific questions not present without a JD
- UI flows cleanly on mobile
- Live transcript displays correctly during a session

---

## Day 10 — Demo & Release

**Goal:** Ship it. Anyone can clone and run in under 10 minutes.

- Record a 3-minute demo: upload resume → voice session → PDF report zoomed in on quote feedback
- Write README: what it is, architecture diagram, quick setup, example report screenshot
- Add `.gitignore`, `requirements.txt`, `docker-compose.yml`
- Push to GitHub

**Verify:**
- Clone on a fresh machine — runs without extra setup steps
- Demo video shows the full flow end-to-end
- README is clear enough for a stranger to get started
