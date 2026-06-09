# Feature Spec — Day 2: Question Bank Generator

**Goal:** `ResumeData` → 28 personalized, validated questions stored in SQLite, ready before the interview starts.

---

## 1. What This Layer Does

Takes the `ResumeData` object produced by Day 1 and generates a fixed bank of 28 questions before the interview session begins. The full bank is ready at session start — no questions are generated in real time during the voice loop.

The output is a `QuestionBank` Pydantic model stored in SQLite, keyed by `session_id`. Every downstream layer — the orchestrator, the scorer, and the report — reads from this bank.

---

## 2. Input

The generator receives a `ResumeData` object. The fields it draws on most heavily:

| Field | How it's used |
|---|---|
| `experience[].company`, `role`, `vague_claims`, `has_metrics` | Source material for behavioral questions |
| `skills.languages`, `skills.frameworks`, `skills.tools` | Source material for technical depth questions |
| `gap_analysis` | Each item must become a gap-probing question |
| `name` | Personalizes question phrasing |
| `experience[].duration_months` | Short tenures are flagged and probed |

---

## 3. Output — 28 Questions in 5 Categories

| Category | Count | What it tests |
|---|---|---|
| Behavioral | 10 | Specific bullets on the resume — what did you do, what was the outcome |
| Technical | 8 | Depth check on claimed skills and tools |
| Gap-probing | 5 | One question per item in `gap_analysis` |
| Situational | 3 | Role-specific judgment hypotheticals |
| Closing | 2 | Self-assessment and what they're looking for next |

**Total: 28**

Each question object also carries:
- `follow_up_vague` — what to say if the answer is short or lacks specifics
- `follow_up_strong` — what to say if the answer is detailed and you want to probe deeper

These are generated alongside the primary question so the orchestrator never needs to call Gemini for basic follow-up logic.

---

## 4. Files to Create

### `backend/schemas/questions.py`

Define two Pydantic models:

**`Question`**
- `id: str` — unique slug, e.g. `"behavioral_01"`, `"gap_02"`
- `category: Literal["behavioral", "technical", "gap_probing", "situational", "closing"]`
- `text: str` — the question the agent will speak
- `source_ref: str` — what resume element this came from (e.g., company name, skill name, gap_analysis index). Empty string for closing questions.
- `follow_up_vague: str` — follow-up text for a weak/short answer
- `follow_up_strong: str` — follow-up text for a strong/detailed answer

**`QuestionBank`**
- `session_id: str`
- `resume_name: str` — copied from `ResumeData.name` for traceability
- `questions: list[Question]`
- Validator: `len(questions) == 28`, fail hard if not exactly 28
- Validator: at least one question per category is present
- Validator: every `gap_probing` question has a non-empty `source_ref` (must trace to a `gap_analysis` item)

**Rule:** If Pydantic validation fails, log the raw LLM output and raise. Never silently coerce or patch. Fix the prompt, not the schema.

---

### `backend/prompts/questions_v1.txt`

The prompt sent to Gemini. Structure:

**System context block**
- You are generating a personalized interview question bank.
- Output must be valid JSON matching the schema below. No commentary, no markdown.
- Every behavioral question must quote or paraphrase a specific bullet from the resume.
- Every gap-probing question must target exactly one item from `gap_analysis`.
- Every question must feel like it could only have been written after reading this specific resume.

**Input injection block**
- Candidate name
- Full `experience` list (company, role, duration_months, has_metrics, vague_claims)
- `skills` (languages, frameworks, tools)
- `gap_analysis` items (numbered list, so the prompt can reference them by index)

**Output schema block**
- Exact JSON structure the model must return
- 28-element array, each element with: `id`, `category`, `text`, `source_ref`, `follow_up_vague`, `follow_up_strong`

**Category-specific instructions**
- Behavioral (10): Reference the exact company name and role. Ask about a specific bullet — not a generic "tell me about yourself." Include what the outcome was and what the candidate's specific contribution was.
- Technical (8): Name the exact skill or tool from the resume. Go beyond surface-level — ask for tradeoffs, debugging experience, or a specific scenario where it was used.
- Gap-probing (5): One question per `gap_analysis` item. Frame as curious, not accusatory. The answer will reveal the gap either way — don't telegraph that you're probing a weakness.
- Situational (3): Role-realistic hypotheticals. Infer the likely target role from experience level and most recent company type.
- Closing (2): Fixed structure — one about what they want next, one about self-assessed weakness. These do not need `source_ref`.

---

### `backend/question_gen/generator.py`

Single function: `generate_question_bank(resume: ResumeData, session_id: str) -> QuestionBank`

**Steps inside the function:**
1. Load prompt template from `backend/prompts/questions_v1.txt`
2. Inject `ResumeData` fields into the prompt (serialize experience and gap_analysis as a readable block, not raw JSON — the LLM reads it more reliably)
3. Call Gemini with `response_mime_type="application/json"` to enforce structured output natively
4. Parse the JSON response
5. Run `QuestionBank.model_validate(parsed)` — if this raises, log the raw output and re-raise
6. Return the validated `QuestionBank`

**No retry logic yet.** If Gemini returns malformed JSON or validation fails, surface the error. Retry can be added if it proves necessary during testing.

**Gemini model:** Gemini 2.5 Flash — same as the parser. Do not introduce a second model.

---

### `backend/db/session.py` — additions

Add two functions to the existing session module (do not create a new file):

**`save_question_bank(bank: QuestionBank) -> None`**
- Creates a `question_banks` table if it does not exist
- Table schema: `(session_id TEXT PK, resume_name TEXT, questions_json TEXT, created_at REAL)`
- Serializes `bank.model_dump()` to JSON and stores it
- Raises on duplicate `session_id` — do not silently overwrite

**`get_question_bank(session_id: str) -> QuestionBank`**
- Fetches the row, deserializes JSON, runs `QuestionBank.model_validate()`
- Raises `KeyError` if no row found for that `session_id`

---

## 5. How the Generator Is Called

For now, the generator is invoked through a CLI entry point for testing. FastAPI wiring comes later (Day 3+).

Create `backend/generate_questions.py` as the CLI entry point:

```
python -m backend.generate_questions <resume_id>
```

**Steps:**
1. Fetch `ResumeData` from SQLite by `resume_id` (using `get_resume()` from Day 1)
2. Generate a `session_id` — use `f"{resume_id}_{timestamp}"` for now
3. Call `generate_question_bank(resume, session_id)`
4. Call `save_question_bank(bank)`
5. Print: `session_id`, question count per category, and all 28 questions with their `source_ref`

---

## 6. `session_id` Convention

For now: `f"{resume_id}_{int(time.time())}"`. No UUID library needed yet. This becomes a proper UUID when the API layer is added in Day 3.

---

## 7. Prompt Engineering Strategy

The key risk is Gemini generating generic questions that could apply to any candidate. The prompt must make this structurally impossible.

**Technique 1 — Force source references.** Every behavioral and gap-probing question requires a `source_ref` field. Gemini must name the specific company, bullet, or gap item. A generic question has nothing to put in `source_ref`.

**Technique 2 — Include the resume as a readable list, not JSON.** The prompt injects experience as:
```
Company: Acme Corp | Role: Software Engineer | Duration: 8 months | Metrics: No
Bullets: "Built internal tools", "Worked with the team on backend services"
```
This format is easier for the model to anchor to than raw JSON.

**Technique 3 — Number the gap_analysis items.** Prompt injects:
```
Gap 1: Short tenure at Acme Corp (8 months) with no explanation
Gap 2: Python listed as a skill but no project uses Python
```
Each gap-probing question must put `"gap_1"` or `"gap_2"` in `source_ref`. Makes it verifiable.

**Technique 4 — Explicit anti-patterns in the prompt.** List what not to generate:
- "Tell me about yourself"
- "What's your greatest strength?"
- "Where do you see yourself in 5 years?"
- Any question that could be asked without reading the resume

---

## 8. Testing Plan

Test on three resume types before marking Day 2 complete.

### Resume types to test
| Type | What to check |
|---|---|
| Junior developer (1–2 years, no metrics, 2–3 jobs) | Gap-probing questions target short tenures; behavioral questions don't over-extrapolate |
| Mid-level engineer (4–6 years, metrics present, 2 employers) | Technical depth questions target specific stack; behavioral questions reference actual outcomes |
| PM / non-engineering background | Situational questions fit the role; technical questions don't assume engineering depth |

### Manual review checklist (per generated bank)
- [ ] Every behavioral question names a specific company or role from the resume
- [ ] Every gap-probing question maps to an item in `gap_analysis` — check `source_ref`
- [ ] Every technical question names a specific skill from `skills` fields
- [ ] `follow_up_vague` is substantively different from `follow_up_strong` for each question
- [ ] No question could have been written without reading this resume (gut check: read each one)
- [ ] 28 total, correct count per category
- [ ] `QuestionBank.model_validate()` passes with no coercion

### Automated checks (run in CLI entry point)
- Print category counts — fail if any category is off
- Print `source_ref` for all behavioral and gap-probing questions — visually confirm they trace to real resume content
- Print one `follow_up_vague` and one `follow_up_strong` from each category — confirm they're meaningfully different

---

## 9. Verification Checklist (from Roadmap)

- [ ] Each behavioral question references a specific resume bullet
- [ ] Each gap-probing question targets something from `gap_analysis`
- [ ] Exactly 28 questions generated
- [ ] Manually read all 28 — every question feels tailored, not generic
- [ ] `QuestionBank` Pydantic validation passes cleanly
- [ ] Questions stored in SQLite and retrievable by `session_id`

---

## 10. What This Spec Does Not Cover

- FastAPI endpoint wiring — Day 3
- Real-time orchestrator integration — Day 3
- Job description targeting — Day 9 (optional JD context adjusts the prompt; schema gets an optional `jd_context` field at that point)
- Retry logic on Gemini failure — add only if testing reveals it's needed
