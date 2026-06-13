# Feature Spec - Day 4: Adaptive Follow-up Logic

**Assumption:** Day 3's voice pipeline and base orchestrator exist; Day 4 refines orchestration behavior only and does not add real scoring, report generation, or new audio providers.

**Goal:** The orchestrator decides whether to follow up, probe deeper, move to the next question, or close the interview based on answer quality, while enforcing a strict maximum of two follow-ups per question.

---

## 1. Data Fetching

**Concern:** Load the question bank and current session state needed to make adaptive decisions without re-reading the resume or regenerating questions.

### Inputs

The adaptive logic uses:

| Source | Data | How it is used |
|---|---|---|
| SQLite `question_banks` table | `QuestionBank` keyed by `session_id` | Provides active question text and prepared follow-ups |
| In-memory `InterviewState` | Current index, follow-up count, transcript log, key facts | Provides conversation state for each decision |
| Incoming transcript event | User's latest final transcript text | The answer being evaluated |
| Question object | `follow_up_vague`, `follow_up_strong`, `category`, `source_ref` | Anchors adaptive response to pre-generated bank |

### Fetch Rules

- The question bank is loaded once when the session starts and stays attached to `InterviewState`.
- Day 4 must not fetch or parse the raw resume again.
- Day 4 must not generate new questions in real time.
- If no active `InterviewState` exists for a `session_id`, the WebSocket/session layer should fail fast instead of creating a partial state.

**Alignment rule:** `session_id` must stay identical across `question_banks`, in-memory `InterviewState`, transcript entries, and event logs. Do not create a replacement session ID during adaptive routing.

---

## 2. `InterviewState`

**Concern:** Track the minimum state needed to decide when to follow up, probe, advance, or close.

### State Fields

| Field | Meaning | Day 4 rule |
|---|---|---|
| `question_bank` | Full 28-question bank | Read-only after session start |
| `current_question_idx` | Active question position | Advances only on `next_question`, skip, or close transition |
| `follow_up_count` | Follow-ups used on active question | Maximum 2; resets to 0 when the question advances |
| `key_facts_mentioned` | Extracted facts from prior answers | Appended after each substantive answer |
| `transcript_log` | Ordered user/agent transcript entries | Must preserve question IDs |
| `session_active` | Whether the interview still accepts transcripts | False after close/session completion |

### Mutation: Append User Answer

- **State it manages:** Adds the latest user transcript to `transcript_log` under the active `question_id`; resets silence tracking for the turn if that is still present from Day 3.
- **Exact API call:** No external API call. This mutation runs before the Gemini decision request.
- **Side effect:** The answer becomes part of the prompt context for the current and future decisions.

### Mutation: Update Key Facts

- **State it manages:** Adds concise facts from the answer to `key_facts_mentioned`, such as metrics, project names, tools, constraints, team size, or outcomes.
- **Exact API call:** Prefer the existing Gemini decision response to include fact extraction if already supported; otherwise perform deterministic local extraction for obvious facts only. Do not add a second LLM call for Day 4.
- **Side effect:** Future follow-ups and transitions can acknowledge prior details without repeating the full transcript.

### Mutation: Increment Follow-up Count

- **State it manages:** Increments `follow_up_count` when the final action is `follow_up` or `probe`.
- **Exact API call:** Gemini decision call returns requested action; local orchestrator guard decides whether this mutation is allowed.
- **Side effect:** The active question remains unchanged; voice pipeline speaks the follow-up text.

### Mutation: Advance Question

- **State it manages:** Increments `current_question_idx`, resets `follow_up_count` to 0, and updates the active `question_id`.
- **Exact API call:** No additional external API call after the Gemini decision response. The orchestrator uses the already-loaded `QuestionBank`.
- **Side effect:** Emits a new `question_asked` event and returns transition text plus the next question to the voice pipeline.

### Mutation: Close Session

- **State it manages:** Sets `session_active = false`; prevents later transcripts from changing state.
- **Exact API call:** Gemini decision call may request `close`, or the orchestrator may close locally when the final question is complete.
- **Side effect:** Returns closing text to TTS and emits a session completion/end event if the existing event logger supports it.

**Alignment rule:** The active `question_id` must always be derived from `question_bank.questions[current_question_idx]`. Never store a separate mutable question ID that can drift from the index.

---

## 3. `handle_transcript` Decision Service

**Concern:** Convert a final user transcript into the next spoken agent response.

### Decision Call

The orchestrator sends one Gemini 2.5 Flash request per substantive answer.

**Exact API call:** Gemini 2.5 Flash content generation with JSON response mode, using `backend/prompts/interviewer_v1.txt` and validating the response with `OrchestratorDecision`.

**Prompt context must include:**

| Context | Required detail |
|---|---|
| Current question | ID, category, text, source reference |
| Prepared follow-ups | Exact `follow_up_vague` and `follow_up_strong` text from the question bank |
| Current answer | User's latest final transcript |
| Recent transcript | Enough recent turns to evaluate completeness without bloating the prompt |
| Key facts | `key_facts_mentioned` accumulated so far |
| Follow-up count | Current count and max of 2 |
| Position | Current question index and total question count |

**Expected model output:**

| Field | Allowed values |
|---|---|
| `action` | `follow_up`, `probe`, `next_question`, `close` |
| `text` | Spoken response text only |

### Mutation: `follow_up`

- **State it manages:** Increments `follow_up_count`; keeps `current_question_idx` unchanged.
- **Exact API call:** Gemini decision response validated as `action = follow_up`.
- **Side effect:** Voice pipeline speaks `decision.text`; no `question_asked` event is emitted because the active question has not changed.

### Mutation: `probe`

- **State it manages:** Increments `follow_up_count`; keeps `current_question_idx` unchanged.
- **Exact API call:** Gemini decision response validated as `action = probe`.
- **Side effect:** Voice pipeline speaks `decision.text`; no `question_asked` event is emitted.

### Mutation: `next_question`

- **State it manages:** Advances `current_question_idx`; resets `follow_up_count`; appends the agent transition/question text to `transcript_log`.
- **Exact API call:** Gemini decision response validated as `action = next_question`; no second Gemini call.
- **Side effect:** Voice pipeline speaks the transition and next question; event logger records `question_asked` for the new active question.

### Mutation: `close`

- **State it manages:** Marks `session_active = false`; appends closing response to `transcript_log`.
- **Exact API call:** Gemini decision response validated as `action = close`, or local close after the last question.
- **Side effect:** Voice pipeline speaks closing text; WebSocket remains able to finish TTS cleanly but should reject new answer handling.

### Local Guard: Follow-up Cap

If Gemini returns `follow_up` or `probe` while `follow_up_count >= 2`, the orchestrator overrides the action to `next_question` locally.

- **State it manages:** Advances question and resets follow-up count instead of incrementing.
- **Exact API call:** No second Gemini call. Reuse the loaded next question from `QuestionBank`.
- **Side effect:** Speaks a graceful transition into the next question and emits `question_asked`.

**Alignment rule:** The LLM can recommend an action, but the orchestrator owns state constraints. The two-follow-up maximum is enforced in Python, not trusted to prompt wording.

---

## 4. Answer Quality Routing

**Concern:** Make follow-ups feel intentional, not random, while staying anchored to the pre-generated bank.

### Vague Answer Route

Use when the answer is too short, abstract, unsupported by examples, or lacks the requested outcome.

- **State it manages:** Counts as one follow-up unless already at the cap.
- **Exact API call:** Gemini decision call should return `follow_up`; prompt must expose the exact `follow_up_vague` text.
- **Side effect:** Agent asks a clarifying follow-up that requests specifics, metrics, ownership, or an example.

### Strong Answer Route

Use when the answer is detailed enough to warrant deeper probing.

- **State it manages:** Counts as one follow-up unless already at the cap.
- **Exact API call:** Gemini decision call should return `probe`; prompt must expose the exact `follow_up_strong` text.
- **Side effect:** Agent asks a deeper follow-up about tradeoffs, constraints, decisions, or lessons learned.

### Complete Answer Route

Use when the answer directly addresses the question with enough detail and no obvious follow-up is needed.

- **State it manages:** Advances to the next question and resets `follow_up_count`.
- **Exact API call:** Gemini decision call should return `next_question`.
- **Side effect:** Agent acknowledges briefly and asks the next question.

### Last Question Route

Use when the current question is the final item in the bank and the answer is complete or the cap is reached.

- **State it manages:** Marks the session inactive.
- **Exact API call:** Gemini decision call may return `close`; otherwise orchestrator closes locally when there is no next question.
- **Side effect:** Agent gives a brief closing statement instead of trying to fetch another question.

**Alignment rule:** Follow-up text may be lightly adapted for conversational flow, but it must remain semantically aligned with the question bank's `follow_up_vague` or `follow_up_strong`. Do not invent unrelated follow-up topics.

---

## 5. Edge Case Routing

**Concern:** Handle common user behavior without wasting a Gemini call or corrupting follow-up counts.

### Repeat Request

- **State it manages:** No change to `current_question_idx` or `follow_up_count`.
- **Exact API call:** No Gemini call.
- **Side effect:** Voice pipeline speaks the active question text again.

### Skip Request

- **State it manages:** Advances to the next question; resets `follow_up_count`; records that the active question was skipped in transcript/event payloads if that convention exists.
- **Exact API call:** No Gemini call.
- **Side effect:** Emits `question_asked` for the next question and speaks it.

### One-word or Near-empty Answer

- **State it manages:** Counts as a vague answer follow-up if below cap; otherwise advances.
- **Exact API call:** Either no Gemini call and use `follow_up_vague` directly, or make the Gemini decision call with `follow_up` as the only allowed action. Prefer the existing Day 3 behavior if already implemented.
- **Side effect:** Agent asks for more detail without sounding punitive.

### Silence Nudge

- **State it manages:** No change to `current_question_idx`; no change to `follow_up_count`.
- **Exact API call:** No Gemini call.
- **Side effect:** Voice pipeline speaks a short nudge and continues listening.

**Alignment rule:** Repeat, skip, one-word fallback, and silence handling must not inflate `follow_up_count` unless the user receives a substantive follow-up to the interview question.

---

## 6. Event Logging

**Concern:** Make adaptive decisions auditable after a session.

### Required Event Behavior

Existing Day 3 events remain authoritative. Day 4 should preserve:

| Event | Day 4 requirement |
|---|---|
| `transcript_received` | Payload question ID must be the question being answered |
| `question_asked` | Emitted only when a new question is asked, not for follow-ups |
| `tts_complete` | Still emitted for follow-ups, probes, transitions, and closing text |
| `interruption` | Still transport-only; does not change adaptive state by itself |

### Optional Event Detail

If event payloads are already easy to extend, include decision metadata in the agent response or a dedicated decision event:

| Field | Meaning |
|---|---|
| `decision_action` | Final action after local guards |
| `model_action` | Raw Gemini action before local override |
| `follow_up_count` | Count after mutation |
| `question_id` | Active or completed question ID, depending on event |

**Alignment rule:** If adding decision metadata, distinguish raw model action from final orchestrator action. This prevents confusion when the follow-up cap overrides Gemini.

---

## 7. Voice Pipeline Wiring

**Concern:** Let the voice pipeline speak whatever the orchestrator returns without gaining interview intelligence.

### Wiring Requirements

- `transcript_received` dispatches final transcript text to the orchestrator.
- The orchestrator returns one spoken response string.
- The voice pipeline sends that string to TTS.
- The voice pipeline does not inspect `action`, `follow_up_count`, answer quality, or question category.

### Mutation: Speak Returned Text

- **State it manages:** Voice pipeline playback state only, such as `is_speaking`.
- **Exact API call:** Google AI Studio TTS/Gemini TTS streaming call already established in Day 3.
- **Side effect:** Browser hears the follow-up, probe, next question, or closing response.

**Alignment rule:** The orchestrator owns interview state. The voice pipeline owns audio state. No Day 4 change should blur that boundary.

---

## 8. UI Surfaces

**Concern:** The browser should reflect the adaptive conversation clearly without exposing internal scoring or decision machinery.

### Live Transcript Surface

- **Previews/prefills:** Displays agent questions, follow-ups, probes, user answers, and closing text in chronological order.
- Follow-ups and probes should appear as normal agent turns, not as separate debug labels.
- If speaker labels exist, the labels must remain `agent` and `user`; do not expose `follow_up` or `probe` as speakers.

### Interview Status Surface

- **Previews/prefills:** Shows the current question number based on `current_question_idx + 1` and total question count.
- The displayed question number should not increase when the agent asks a follow-up or probe.
- The displayed question number should increase only when `question_asked` fires for a new question.

### Control Surface

- **Previews/prefills:** Existing repeat, skip, and end controls should map to the same behavior as spoken commands if those controls exist.
- Repeat should replay the current question without changing progress.
- Skip should advance to the next question and reset follow-up count.

**Alignment rule:** UI progress must track question advancement, not agent turns. Follow-ups add transcript rows but do not count as new questions.

---

## 9. Prompt Alignment

**Concern:** The interviewer prompt must make the model choose among existing actions instead of inventing a new interview flow.

### Prompt Rules

- The model is not generating new interview questions.
- The model chooses the next action for the current answer.
- The model must use or lightly adapt the prepared vague/strong follow-up texts.
- The model must output JSON only.
- The `text` field must be spoken language only: no markdown, headings, score labels, or internal reasoning.
- The model must not mention the words "vague answer", "probe", "rubric", "score", or "follow-up count" to the user.

**Alignment rule:** The prompt and `OrchestratorDecision` schema must agree on the exact action names: `follow_up`, `probe`, `next_question`, `close`.

---

## 10. Check When Done

- [ ] Give a vague answer and the agent asks the prepared vague follow-up or a close adaptation of it.
- [ ] Give a strong, detailed answer and the agent probes deeper using the prepared strong follow-up or a close adaptation of it.
- [ ] Give a complete answer and the agent moves smoothly to the next question.
- [ ] Give three weak answers on the same question and the agent moves on after two follow-ups.
- [ ] The question number in the UI does not advance during follow-ups or probes.
- [ ] Repeat request replays the current question without calling Gemini and without changing `follow_up_count`.
- [ ] Skip request advances to the next question, resets `follow_up_count`, and emits `question_asked`.
- [ ] `question_asked` events are emitted only for new questions, not follow-ups.
- [ ] `transcript_log` entries for follow-ups retain the same `question_id` as the original question.
- [ ] Last question closes the session gracefully instead of attempting to advance past the bank.
- [ ] Raw Gemini action and final orchestrator action are distinguishable in logs if decision metadata is added.
- [ ] Voice pipeline code still contains no interview decision logic.
- [ ] Orchestrator tests can replay transcripts without microphone, Deepgram, VAD, or TTS.
