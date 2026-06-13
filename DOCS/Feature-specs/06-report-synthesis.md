# Feature Spec 06 - Report Synthesis

**Roadmap reference:** Day 6

**Assumption:** Day 6 produces a validated `ReportData` object from existing question bank, transcript, and score records only; PDF rendering, download endpoints, and visual report styling remain Day 7 work.

---

## 1. Data Fetching

**Concern:** Gather every persisted input required to synthesize a session report without re-running parsing, question generation, interview decisions, or scoring.

### Inputs

| Source | Data | How it is used |
|---|---|---|
| SQLite `question_banks` table | `QuestionBank` keyed by `session_id` | Provides question text, category, source refs, and intended interview structure |
| SQLite `scores` table | `ScoreResult` rows keyed by `session_id` | Provides validated per-answer scores, moments, and rewrites |
| Session transcript storage | User and agent transcript entries grouped by `question_id` | Provides exact candidate quotes for feedback and action items |
| Event log, optional | `question_asked`, `transcript_received`, `scoring_complete` timing | Used only for diagnostics if report synthesis detects missing inputs |

### Fetch Rules

- Load the question bank once by `session_id` through the existing `get_question_bank(session_id)` helper.
- Load score rows once through `get_scores(session_id)`, ordered by timestamp.
- Load transcripts through the current transcript persistence helper if one exists; if transcripts are only in memory today, Day 6 must add a read path before synthesis can be considered complete.
- Do not call Gemini to regenerate missing questions, transcripts, or scores.
- Do not read the raw resume text for report synthesis. The report is based on the interview session, not a fresh resume analysis pass.

### Alignment Constraints

- `session_id` must stay identical across question bank, transcript entries, score rows, and report synthesis.
- `question_id` is the join key across `Question.id`, `TranscriptEntry.question_id`, `ScoreResult.question_id`, and report feedback. IDs must stay in sync.
- Every non-skipped score used in a report must map to exactly one question from the question bank.
- Skipped score rows may appear in the report, but they must not drag down aggregate averages.
- Missing score rows are a hard synthesis error unless the session was explicitly ended before that question was reached.

---

## 2. `ReportData` Schema - `backend/schemas/report.py`

**Concern:** Define the validated data contract that Day 7 can render to PDF without extra interpretation.

### Top-level Fields

| Field | Type | Notes |
|---|---|---|
| `session_id` | `str` | Same ID used by question bank, scores, transcripts |
| `resume_name` | `str` | From `QuestionBank.resume_name` |
| `generated_at` | `str` | ISO timestamp in UTC |
| `overall_score` | `float` | 1-10 aggregate from non-skipped answers |
| `dimension_breakdown` | `DimensionBreakdown` | Average scores by dimension |
| `category_breakdown` | `list[CategoryScore]` | Average overall score per question category |
| `top_moments` | `TopMoments` | Best answer, weakest answer, and missed opportunity |
| `per_question_feedback` | `list[QuestionFeedback]` | One feedback item for each answered or skipped question included in the session |
| `action_items` | `list[ActionItem]` | Exactly five prioritized coaching actions |

### Nested Model: `DimensionBreakdown`

| Field | Type | Notes |
|---|---|---|
| `relevance` | `float` | Average of non-skipped `ScoreResult.relevance` |
| `specificity` | `float` | Average of non-skipped `ScoreResult.specificity` |
| `structure` | `float` | Average of non-skipped `ScoreResult.structure` |
| `communication` | `float` | Average of non-skipped `ScoreResult.communication` |

### Nested Model: `CategoryScore`

| Field | Type | Notes |
|---|---|---|
| `category` | `str` | Must match question category from the bank |
| `average_score` | `float` | Average `ScoreResult.overall` for non-skipped answers in this category |
| `answered_count` | `int` | Non-skipped answered questions in this category |
| `skipped_count` | `int` | Skipped questions in this category |

### Nested Model: `TopMoments`

| Field | Type | Notes |
|---|---|---|
| `best_answer_question_id` | `str` | Question ID with strongest non-skipped score or strongest moment |
| `best_answer_quote` | `str` | Exact candidate quote from transcript |
| `weakest_answer_question_id` | `str` | Question ID with weakest non-skipped score |
| `weakest_answer_quote` | `str` | Exact candidate quote from transcript |
| `missed_opportunity_question_id` | `str` | Question where a stronger answer could materially improve the interview |
| `missed_opportunity_summary` | `str` | Specific coaching note grounded in the answer |

### Nested Model: `QuestionFeedback`

| Field | Type | Notes |
|---|---|---|
| `question_id` | `str` | Must match a question from `QuestionBank` |
| `category` | `str` | Copied from the question bank |
| `question_text` | `str` | Original question text |
| `answer_quote` | `str \| None` | Exact candidate quote; null when skipped or no answer exists |
| `score` | `float \| None` | `ScoreResult.overall`; null when skipped |
| `strength` | `str \| None` | User-facing summary of what worked |
| `improvement_area` | `str \| None` | User-facing summary of what was weak |
| `suggested_rewrite` | `str \| None` | First-person rewrite from or derived from scoring data |
| `skipped` | `bool` | Mirrors `ScoreResult.skipped` |

### Nested Model: `ActionItem`

| Field | Type | Notes |
|---|---|---|
| `priority` | `int` | 1-5, unique |
| `title` | `str` | Short coaching label |
| `why_it_matters` | `str` | Specific reason based on this session |
| `example_from_session` | `str` | Exact quote or specific paraphrase from transcript |
| `practice_instruction` | `str` | Concrete action the candidate can take before the next interview |

### Validation Rules

- `overall_score` and all averages must be between 1 and 10 and rounded to one decimal.
- `action_items` must contain exactly five items with unique priorities 1 through 5.
- `per_question_feedback.question_id` values must all exist in the loaded question bank.
- Non-skipped `QuestionFeedback` rows require `answer_quote`, `score`, `strength`, `improvement_area`, and `suggested_rewrite`.
- Skipped `QuestionFeedback` rows require `score = null`; text feedback may be null or a short skipped-answer note.
- `answer_quote`, `best_answer_quote`, and `weakest_answer_quote` must be anchored to transcript text, not invented by Gemini.

---

## 3. Report Synthesis Prompt - `backend/prompts/report_v1.txt`

**Concern:** Ask Gemini to turn validated session data into user-facing report content while preserving exact quotes and score integrity.

### Injected Fields

| Placeholder | Source |
|---|---|
| `{session_id}` | Synthesis input |
| `{resume_name}` | `QuestionBank.resume_name` |
| `{score_summary}` | Deterministic summary of averages and category scores |
| `{question_feedback_inputs}` | Per-question question text, category, score result, and transcript excerpts |
| `{allowed_quotes}` | Exact candidate quotes that Gemini may use |

### Expected JSON Output

The prompt must ask for JSON matching `ReportData` excluding deterministic fields that the synthesizer owns:

| Field | Owned by |
|---|---|
| `session_id` | Synthesizer |
| `resume_name` | Synthesizer |
| `generated_at` | Synthesizer |
| `overall_score` | Synthesizer |
| `dimension_breakdown` | Synthesizer |
| `category_breakdown` | Synthesizer |
| `top_moments` | Gemini proposes, synthesizer validates |
| `per_question_feedback` | Gemini writes narrative fields, synthesizer validates IDs and scores |
| `action_items` | Gemini writes, synthesizer validates count and quote grounding |

### Prompt Rules

- Gemini must not recompute numeric scores.
- Gemini must not change question IDs, categories, or score values.
- Gemini must only use quotes from `{allowed_quotes}`.
- Feedback should explain what the user said, why it was strong or weak, and how to improve it.
- Suggested rewrites must be in first person, as if the candidate is answering again.
- Action items must be specific to this session; generic items like "be more specific" are invalid unless tied to an exact quote.
- The prompt must be used with Gemini JSON response mode.

---

## 4. `synthesize_report` Service - `backend/report/synthesizer.py`

**Concern:** Coordinate fetching, deterministic aggregation, Gemini narrative synthesis, validation, and persistence handoff.

### Public Entry Point

`synthesize_report(session_id) -> ReportData`

### Mutation: Load Session Inputs

- **State it manages:** No long-lived in-memory state. Builds a local immutable synthesis input bundle.
- **Exact API call:** `get_question_bank(session_id)`, `get_scores(session_id)`, and transcript fetch helper for the same `session_id`.
- **Side effect:** None. If required inputs are missing, raise a clear synthesis error before calling Gemini.

### Mutation: Build Deterministic Aggregates

- **State it manages:** Computes local aggregate values for `overall_score`, `dimension_breakdown`, and `category_breakdown`.
- **Exact API call:** No external API call.
- **Side effect:** Produces numeric fields that Gemini is not allowed to override.

### Mutation: Call Gemini for Narrative Report Content

- **State it manages:** Creates candidate-facing narrative fields: top moments, strengths, improvement areas, rewrites, and action items.
- **Exact API call:** Gemini 2.5 Flash content generation using `backend/prompts/report_v1.txt` with `response_mime_type="application/json"`.
- **Side effect:** None outside the function. The raw output is parsed and validated before any caller can use it.

### Mutation: Validate and Assemble `ReportData`

- **State it manages:** Merges deterministic numeric fields with Gemini narrative fields into a single `ReportData`.
- **Exact API call:** `ReportData.model_validate(...)`.
- **Side effect:** Returns validated report data to the caller. Day 6 does not render PDF or navigate the UI.

### Error Handling

- If score rows are missing for answered questions, raise before Gemini.
- If Gemini returns malformed JSON, raise a report synthesis validation error.
- If Gemini invents a quote not present in `allowed_quotes`, validation must fail.
- If `ReportData` validation fails, log raw Gemini output and raise. Do not silently coerce report content.

---

## 5. Transcript-to-Feedback Mapping

**Concern:** Ensure every report statement can be traced back to what happened in the interview.

### Mapping Rules

- Group transcript entries by `question_id`.
- For each question, extract candidate/user turns only for answer quotes.
- Agent turns may be used for question context but not as candidate evidence.
- If multiple user turns exist for a question due to follow-ups, combine them as one answer context for report synthesis.
- Use the strongest concise quote from user turns as `answer_quote`; avoid long multi-paragraph transcript dumps.
- Follow-up answers stay attached to the original `question_id`; they do not become separate report items.

### Alignment Constraints

- The number of `per_question_feedback` rows should match the number of reached questions, not necessarily all 28 questions.
- If an interview ended early, unreached questions must not appear as skipped.
- If a user explicitly skipped a reached question, include it with `skipped = true`.
- Feedback order must follow interview order from the question bank.

---

## 6. Persistence and API Boundary

**Concern:** Make Day 6 usable by tests and Day 7 without prematurely adding PDF behavior.

### Persistence Decision

Day 6 does not need a permanent `reports` table unless the implementation wants cached synthesis. The default behavior is on-demand synthesis from persisted scores and transcripts.

### Optional Mutation: Save Synthesized Report

- **State it manages:** Stores a serialized `ReportData` snapshot if caching is implemented.
- **Exact API call:** New `save_report(session_id, report_data)` helper in `backend/db/session.py`, only if needed by the implementor.
- **Side effect:** Future `get_report(session_id)` calls can return the same report without re-calling Gemini.

### API Surface

No user-facing HTTP endpoint is required for Day 6. If an internal route is added for manual testing, it must return JSON `ReportData` only and must not attempt PDF rendering.

### UI Surfaces

Day 6 does not create new UI. It defines the data that future UI/PDF surfaces will preview:

| Future surface | What it previews or pre-fills |
|---|---|
| Report preview card | `overall_score`, `dimension_breakdown`, and top action item |
| Full PDF report | All `ReportData` fields |
| Per-question feedback section | `per_question_feedback` in interview order |
| Score trend/history UI | `overall_score` and category/dimension breakdowns if reused by Day 8 |

---

## 7. Tests and Fixtures

**Concern:** Verify report synthesis before any real PDF rendering exists.

### Test Inputs

- Mock question bank with at least five questions across multiple categories.
- Mock score rows including strong, weak, and skipped answers.
- Mock transcript entries with multiple user turns on at least one question.
- One fixture where a score row references a missing `question_id`.
- One fixture where Gemini returns an invented quote.

### Required Checks

- Aggregates ignore skipped answers.
- Category averages use question categories from `QuestionBank`, not Gemini output.
- Per-question feedback follows question bank order.
- Missing score/question alignment raises before Gemini.
- Invented quotes fail validation.
- `ReportData` validates cleanly for a complete fixture.

---

## 8. Check When Done

- [ ] `backend/schemas/report.py` defines `ReportData` and nested models with validation for score ranges, action item count, question IDs, and quote grounding.
- [ ] `backend/prompts/report_v1.txt` instructs Gemini to produce narrative report content without recomputing scores or inventing quotes.
- [ ] `backend/report/synthesizer.py` exposes `synthesize_report(session_id) -> ReportData`.
- [ ] Synthesis loads question bank, scores, and transcripts by the same `session_id`.
- [ ] `question_id` alignment is enforced across question bank, score rows, transcripts, and feedback rows.
- [ ] Overall and dimension/category averages are computed deterministically from `ScoreResult`, not by Gemini.
- [ ] Skipped answers are included as skipped feedback when reached, but excluded from numeric averages.
- [ ] Follow-up transcript turns stay attached to their original question feedback item.
- [ ] Every action item references a specific transcript quote or session-specific detail.
- [ ] Gemini-invented quotes fail validation instead of appearing in the report.
- [ ] Mock score data can synthesize a complete `ReportData` object before using a real Day 5 session.
- [ ] Running synthesis on a real Day 5 session produces valid `ReportData` ready for Day 7 PDF rendering.
