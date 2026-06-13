# Feature Spec 05 — Silent Per-Answer Scoring

**Roadmap reference:** Day 5

---

**Assumptions (stated explicitly):**

- Scoring runs inside the orchestrator process via `asyncio.create_task()` — no separate worker, queue, or process. The existing placeholder `_score_answer` call site in `orchestrator.py` is the wiring point.
- Skipped answers are stored with `skipped: true` and all numeric score fields set to `null` — not `0` — so downstream aggregation does not penalise them.
- Scoring dimensions are: `relevance`, `specificity`, `structure`, `communication`, each scored 1–10, plus a derived `overall` (arithmetic mean, rounded to one decimal).
- `score_answer_async` is the public entry point; it is not `async def` by convention of being called with `asyncio.create_task()` — it is an `async def` coroutine.
- Scores table is added in `backend/db/session.py` (same module, same pattern as resumes and question banks) — no new db module.
- Gemini 2.5 Flash is used for scoring, matching every other LLM call in the project.

---

## 1. ScoreResult Schema — `backend/schemas/scoring.py`

**What it models:** The validated output of one Gemini scoring call for one question-answer pair.

**Fields:**

| Field | Type | Notes |
|---|---|---|
| `question_id` | `str` | Matches `Question.id` from the question bank |
| `skipped` | `bool` | If true, all numeric fields are `null` |
| `relevance` | `int \| None` | 1–10; null when skipped |
| `specificity` | `int \| None` | 1–10; STAR completeness — are Situation/Task/Action/Result present? |
| `structure` | `int \| None` | 1–10; logical flow, coherence |
| `communication` | `int \| None` | 1–10; clarity, conciseness, tone |
| `overall` | `float \| None` | Arithmetic mean of the four dimensions, rounded to 1 decimal; null when skipped |
| `strongest_moment` | `str \| None` | Verbatim quote or paraphrase of the best thing said; null when skipped |
| `weakest_moment` | `str \| None` | Verbatim quote or paraphrase of the weakest part; null when skipped |
| `suggested_rewrite` | `str \| None` | One improved phrasing of the weakest moment; null when skipped |

**Validation rules:**

- If `skipped` is `true`, all numeric and text fields must be `null`. Validator raises if any numeric field is non-null on a skipped record.
- Each numeric field, when not null, must be an integer in [1, 10]. Validator coerces float → int (LLMs sometimes return `7.0`).
- `overall` is **computed by the validator** from the four dimensions — Gemini does not return it. This ensures consistency and prevents prompt drift affecting the aggregate.
- `strongest_moment` and `weakest_moment` must be non-empty strings when not null. The validator strips whitespace and rejects empty-after-strip.

---

## 2. Scoring Prompt — `backend/prompts/scoring_v1.txt`

**What it receives (injected fields via `.format()`):**

| Placeholder | Source |
|---|---|
| `{question_text}` | `Question.text` |
| `{question_category}` | `Question.category` |
| `{answer_transcript}` | Formatted string of user turns only (speaker=user), joined by `\n` |
| `{is_skipped}` | `"true"` or `"false"` |

**What it must return (JSON schema to specify in the prompt):**

```
{
  "relevance": <int 1–10 or null>,
  "specificity": <int 1–10 or null>,
  "structure": <int 1–10 or null>,
  "communication": <int 1–10 or null>,
  "strongest_moment": <string or null>,
  "weakest_moment": <string or null>,
  "suggested_rewrite": <string or null>
}
```

**Prompt design constraints:**

- Instruct Gemini to return all nulls when `is_skipped` is `"true"` — no scores, no moments.
- For `specificity`, instruct Gemini to look for the four STAR elements (Situation, Task, Action, Result) and score on how many are clearly present and grounded.
- Forbid Gemini from referencing the scoring rubric in `suggested_rewrite`. The rewrite must sound like natural speech, not a coaching note.
- `strongest_moment` and `weakest_moment` must reference something the candidate **actually said** — the prompt must forbid generic observations like "lacked specifics."
- Prompt must request `response_mime_type="application/json"` (enforced in the caller, not the prompt text — note this here for implementor awareness).

---

## 3. Scorer — `backend/scoring/scorer.py`

**Module responsibilities:** Call Gemini with the scoring prompt, validate the response through `ScoreResult`, persist to SQLite, emit `scoring_complete` event.

### `score_answer_async(session_id, question_id, question_text, question_category, transcript, skipped)`

**State managed:** None in-memory. All state is persisted to SQLite via `save_score()`.

**Exact Gemini call:**
- Model: `gemini-2.5-flash`
- Config: `response_mime_type="application/json"`, temperature not set (use model default for scoring — determinism is preferable).
- Called via `loop.run_in_executor(None, lambda: ...)` — same pattern as `_call_gemini` in `orchestrator.py`.

**Input preparation:**
- Filter `transcript` to `speaker == "user"` entries only before injecting into the prompt. Agent turns are not part of the answer being scored.
- If `skipped` is `True`, still call this function — it writes a null-score record so every question has a row.

**Validation:**
- Parse Gemini response as JSON, then `ScoreResult.model_validate(...)`.
- If validation fails: log the error with `logger.error`, log a `scoring_complete` event with `{"error": "validation_failed", "question_id": ...}`, and return — do not raise.

**Persistence:**
- Call `save_score(session_id, question_id, score_result)` after successful validation.

**Event emission:**
- After `save_score` completes, call `log_event(session_id, EVT_SCORING_COMPLETE, {...})`.
- Payload shape: `{"question_id": question_id, "overall": score_result.overall, "skipped": score_result.skipped, "scoring_duration_ms": <int>}`.
- `scoring_duration_ms` is measured from the start of the Gemini call, not from when `score_answer_async` is invoked.

**Error isolation:**
- The entire function body must be wrapped so no exception propagates out. A scoring failure must never affect the voice session. If any step fails unexpectedly, log and return silently.

---

## 4. SQLite — Scores Table

**Location:** `backend/db/session.py` — new functions added alongside `save_resume`, `save_question_bank`, etc.

### Table schema — `scores`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `session_id` | TEXT NOT NULL | |
| `question_id` | TEXT NOT NULL | |
| `skipped` | INTEGER NOT NULL | 0 or 1 (SQLite boolean) |
| `scores_json` | TEXT NOT NULL | Full `ScoreResult` serialised as JSON |
| `ts` | REAL NOT NULL | Unix timestamp at time of insert |

**Unique constraint:** `(session_id, question_id)` — one score row per question per session. Insert fails loudly if a duplicate is attempted (do not silently overwrite).

### `save_score(session_id, question_id, score_result: ScoreResult) -> None`

- Calls `_ensure_scores_table(conn)` before inserting (same lazy-init pattern used for events).
- Serialises `score_result` via `score_result.model_dump_json()`.
- Raises `sqlite3.IntegrityError` on duplicate — the caller (`score_answer_async`) must catch and log this without crashing.

### `get_scores(session_id) -> list[ScoreResult]`

- Returns all `ScoreResult` objects for a session, ordered by `ts ASC`.
- Deserialises each row's `scores_json` via `ScoreResult.model_validate_json(...)`.
- Returns empty list if no rows found.

---

## 5. Orchestrator Wiring — `backend/orchestrator/orchestrator.py`

**Change scope:** Replace the body of the existing `_score_answer` placeholder with a delegation call to the real scorer.

**Current placeholder signature:**
```
async def _score_answer(session_id, question_id, question_text, transcript, skipped=False)
```

**Required change:**
- Import `score_answer_async` from `backend.scoring.scorer`.
- Replace placeholder body with: `await score_answer_async(session_id, question_id, question_text, question_category, transcript, skipped)`.
- `question_category` must be threaded through from `_advance_question`, where `completed_q.category` is already available.

**Alignment constraint:** The `_score_answer` call site in `_advance_question` fires via `asyncio.create_task()`. The real scorer must not block — it must return control immediately to the event loop. Any synchronous Gemini call inside must be wrapped with `run_in_executor`.

**Alignment constraint:** `question_id` passed into `_score_answer` must match the `question_id` stored in the `events` table for `question_asked`. These IDs are the join key for all downstream reporting (Day 6). They must never diverge.

---

## 6. Event Logging — `backend/db/events.py`

**No new event type needed.** `EVT_SCORING_COMPLETE = "scoring_complete"` is already defined.

**Payload shape for `scoring_complete` (success path):**

```json
{
  "question_id": "<str>",
  "overall": <float | null>,
  "skipped": <bool>,
  "scoring_duration_ms": <int>
}
```

**Payload shape for `scoring_complete` (error path):**

```json
{
  "question_id": "<str>",
  "error": "validation_failed",
  "scoring_duration_ms": <int>
}
```

**Timing invariant:** The `scoring_complete` event timestamp must always be **after** the `question_asked` event for the **next** question (or `session_end` for the last question). This confirms non-blocking behaviour. This is a verification item, not enforced in code — the `ts` column in the events table is the observable.

---

## Check When Done

- [ ] Run a full session (5+ questions). Query `SELECT * FROM scores WHERE session_id = ?` — one row exists per question, including the last.
- [ ] Skipped questions have `skipped = 1` in the scores table and `null` for all numeric fields in `scores_json`.
- [ ] `ScoreResult.overall` is the arithmetic mean of the four dimension scores, not returned by Gemini directly.
- [ ] Query `events` table: every `scoring_complete` row has a `ts` value **greater than** the `ts` of the subsequent `question_asked` row (or `session_end`). This proves scoring did not block the voice turn.
- [ ] Inject a deliberately malformed Gemini response (e.g. by temporarily breaking the prompt). Confirm: session continues, `scoring_complete` event is written with `"error": "validation_failed"`, no exception reaches the voice pipeline.
- [ ] `scores_json` for a non-skipped answer contains `strongest_moment` and `weakest_moment` that reference something from the transcript, not generic coaching language.
- [ ] `suggested_rewrite` reads as natural speech — not "You should have said X" but "Here is how I could have phrased that: ...".
- [ ] `get_scores(session_id)` returns all rows in timestamp order and deserialises cleanly through `ScoreResult.model_validate_json`.
- [ ] Duplicate score insert (same `session_id` + `question_id`) raises `IntegrityError` and is caught — does not crash anything.
