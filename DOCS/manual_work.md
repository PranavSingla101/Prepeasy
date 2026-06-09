# Manual Work — Things You Must Do Yourself

Everything here requires your action. Claude cannot do these for you (account signups, API keys, live testing, recording, publishing).

---

## Day 1 — Resume Parser (current)

### [ ] 1. Get a Gemini API key and add it to `.env`

1. Go to [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Create a new key
3. Open `.env` in the project root and replace the placeholder:
   ```
   GEMINI_API_KEY=your_actual_key_here
   ```

### [ ] 2. Run live verification against the sample resume

```powershell
cd c:\Users\LENOVO\Documents\project\Interview-Agent
Interv\Scripts\python.exe -m backend.parse_resume DOCS/Pranav-GTM-intern.pdf
```

Then manually check every item in `DOCS/Feature-specs/01-resume-parser.md` verification checklist:
- Raw text > 200 characters
- JSON output has `name`, `skills`, `experience`, `gap_analysis`
- `gap_analysis` contains real observations
- `has_metrics` / `vague_claims` reflect the actual resume
- SQLite row created in `data/interviews.db`
- Total run time under 10 seconds

### [ ] 3. Test on 2 more resumes of different formats

The spec requires at least 3 resumes total. Get 2 more PDF resumes (your own or colleagues') and run the parser on each. Look for edge cases: sparse resumes, scanned PDFs, multi-page.

---

## Day 2 — Question Bank

### [ ] 4. Run the question generator against your Day 1 resume

Use the `resume_id` printed when you ran the parser:

```powershell
cd c:\Users\LENOVO\Documents\project\Interview-Agent
Interv\Scripts\python.exe -m backend.generate_questions <resume_id>
```

### [ ] 5. Manually read all 28 generated questions

Read every question in the printed output. This is a judgment call only you can make:
- Does each **behavioral** question name a specific company or role from your resume?
- Does each **gap-probing** question trace to a real item in `gap_analysis` — check the printed `source_ref`?
- Does each **technical** question name a specific skill from your resume?
- Is `follow_up_vague` substantively different from `follow_up_strong` for each question?
- Could any question have been written without reading this resume? If yes, the prompt needs tuning.

### [ ] 6. Test on 2 more resume types

The spec requires testing on 3 resume types: junior dev, mid-level engineer, PM. Run the full pipeline (parse → generate) on 2 more PDFs and read the output for each:

```powershell
Interv\Scripts\python.exe -m backend.parse_resume <path/to/resume2.pdf>
Interv\Scripts\python.exe -m backend.generate_questions <resume2_id>
```

Check that:
- Gap-probing questions shift based on each resume's actual weaknesses
- Technical questions match the skills on each resume — no cross-contamination
- Category counts are always exactly: behavioral 10, technical 8, gap_probing 5, situational 3, closing 2

### [ ] 7. Verify SQLite storage

Confirm the question bank is persisted and retrievable:

```powershell
Interv\Scripts\python.exe -c "from backend.db.session import get_question_bank; b = get_question_bank('<session_id>'); print(len(b.questions), 'questions')"
```

---

## Day 3 — Voice Pipeline

### [x] 8. Sign up for Deepgram and get an API key

- DONE — key already added to `.env` as `DEEPGRAM_API_KEY`

### No TTS key needed — Google AI Studio TTS uses the same `GEMINI_API_KEY`

### [ ] 9. Start the server and confirm it boots clean

```powershell
cd c:\Users\LENOVO\Documents\project\Interview-Agent
Interv\Scripts\uvicorn backend.main:app --reload --port 8000
```

Expected: no import errors, `Uvicorn running on http://0.0.0.0:8000` in the log. Hit `http://localhost:8000/health` and confirm `{"status": "ok"}`.

### [ ] 10. Run the orchestrator in isolation (no audio, no Deepgram)

Replay a hardcoded transcript list to confirm decision logic without any voice pipeline code loaded:

```powershell
Interv\Scripts\python.exe -c "
import asyncio, os
from dotenv import load_dotenv; load_dotenv()
from backend.orchestrator import orchestrator

session_id = '<your_session_id_from_generate_questions>'
first_q = orchestrator.start_session(session_id)
print('Q1:', first_q)

async def run():
    r1 = await orchestrator.handle_transcript(session_id, 'I led the team and we shipped on time.')
    print('Agent:', r1)
    r2 = await orchestrator.handle_transcript(session_id, 'Yes.')   # one-word — must trigger follow_up
    print('Agent (should follow up):', r2)

asyncio.run(run())
"
```

Confirm:
- First response acknowledges the answer and continues naturally
- One-word answer triggers a follow-up (not `next_question`)
- No audio code is involved — pure Python

### [ ] 11. Run a live 5-question voice session with yourself

Connect from a browser using a WebSocket test client (e.g. [https://www.piesocket.com/websocket-tester](https://www.piesocket.com/websocket-tester) or write a small HTML page) to:

```
ws://localhost:8000/ws/interview/<session_id>
```

Speak 5 full answers without skipping. Verify:
- The agent's voice sounds natural and not robotic
- Transitions between questions are smooth — no dead silence, no overlap
- Transcripts appear in the browser as `{"type": "transcript", ...}` text frames
- TTS audio arrives as binary frames

No automated test can replace this — you have to sit through it.

### [ ] 12. Check the events table after the session

After the 5-question session, query the events table and confirm the event sequence is correct:

```powershell
Interv\Scripts\python.exe -c "
import sqlite3, json
c = sqlite3.connect('data/interviews.db')
rows = c.execute('SELECT event_type, ts, payload FROM events WHERE session_id=? ORDER BY ts', ('<session_id>',)).fetchall()
for ev_type, ts, payload in rows:
    print(ev_type, json.loads(payload).get('question_id',''))
"
```

Expected pattern per question: `question_asked` → `vad_start` → `vad_end` → `transcript_received` → (next) `question_asked`. All rows present, timestamps in order.

### [ ] 13. Verify follow-up cap: give a one-word answer three times

For one question, give three one-word answers in a row (e.g. "Yes.", "Sure.", "Okay."). Confirm the agent moves on after **2** follow-ups, not 3. If it asks a third follow-up, the follow-up count guard is broken.

### [ ] 14. Test the repeat edge case

Mid-question, say "Can you repeat that?" Confirm:
- The same question is spoken again
- `follow_up_count` is unchanged (check the events table — no new `question_asked` event)
- No Gemini call was made (no latency spike)

### [ ] 15. Test barge-in (interrupt mid-TTS)

While the agent is speaking, start talking. Confirm:
- TTS stops immediately
- An `interruption` event is logged in the events table with a non-zero `tts_elapsed_ms`
- Deepgram picks up your speech correctly after the interruption

### [ ] 16. Test silence nudge

Stay completely silent for 10+ seconds after a question is asked. Confirm:
- The agent says "Take your time, or say 'skip' to move on."
- `silence_streak` resets to 0 (next silence window starts fresh)
- No nudge fires while TTS is already playing

### [ ] 17. Confirm scoring events are non-blocking

After a session, check the `scoring_complete` event timestamps. Each `scoring_complete` timestamp must be **after** the next `question_asked` timestamp — scoring must never hold up the voice loop:

```powershell
Interv\Scripts\python.exe -c "
import sqlite3, json
c = sqlite3.connect('data/interviews.db')
rows = c.execute('SELECT event_type, ts FROM events WHERE session_id=? ORDER BY ts', ('<session_id>',)).fetchall()
for t, ts in rows:
    print(f'{t:25} {ts:.3f}')
"
```

### [ ] 18. Confirm no cross-boundary imports

```powershell
grep -r 'from backend.orchestrator' backend/voice_pipeline/
```

Expected: only `backend/voice_pipeline/events.py` appears (the authorised event bus). No other voice_pipeline file should import orchestrator.

```powershell
grep -r 'from backend.voice_pipeline' backend/orchestrator/
```

Expected: no output.

---

## Day 4 — Adaptive Follow-ups

### [ ] 10. Test follow-up logic with intentionally weak and strong answers

Give the agent a deliberately vague answer (e.g., "I just kind of helped the team") and verify it triggers `follow_up_if_vague`. Then give a strong, specific answer and verify it either probes deeper or moves on. You must do this manually — it requires natural language judgment.

---

## Day 5 — Scoring

### [ ] 11. Run a full 20-minute session and check SQLite scores

After session ends, open the DB and confirm a score row exists for every answer:

```powershell
Interv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect('data/interviews.db'); print(c.execute('SELECT * FROM scores').fetchall())"
```

---

## Day 6 — Report Synthesis

### [ ] 12. Read the generated report JSON critically

Check every `action_items` entry — they must reference specific things you said, not generic advice. If any item says something like "be more specific" without quoting you, the synthesis prompt needs tuning. This requires reading the output yourself.

---

## Day 7 — PDF Report

### [ ] 13. Visual QA the PDF on mobile and desktop

Open the generated PDF on your phone and on a laptop. Check:
- Score bars render correctly
- Quote blocks don't overflow
- Fonts and layout look professional
- Looks good enough to screenshot and share

---

## Day 8 — Session History

### [ ] 14. Run 3 sessions and verify score trend is accurate

Manually run 3 interview sessions. After each, check that the trend data in the UI or PDF reflects the real scores from SQLite — not dummy/stale data.

---

## Day 9 — JD Targeting

### [ ] 15. Paste a real job description and verify tailored questions

Find a real JD (LinkedIn, Greenhouse, etc.). Paste it into the upload page. Read the generated question bank — at least a few questions should be role-specific and wouldn't exist without the JD.

---

## Day 10 — Demo & Release

### [ ] 16. Record a 3-minute Loom demo video

Script:
- 0:00–0:30 — Upload your resume, show the structured JSON / gap analysis output
- 0:30–2:00 — Run a 5-question voice session, show the live transcript
- 2:00–3:00 — Open the PDF report, zoom into a quote-anchored feedback block

### [ ] 17. Write the README

Must include: what it is, architecture diagram (copy from `DOCS/Project-info-detailed.md`), quick setup instructions, example report screenshot.

### [ ] 18. Push to GitHub

```bash
git init
git add .
git commit -m "initial release"
gh repo create interview-agent --public
git push -u origin main
```

Verify the repo is public and someone else can clone + run it in under 10 minutes.

### [ ] 19. Write and publish the launch post

400-word post for dev.to and/or LinkedIn:
- Title: "I built a voice interview coach that reads your resume and scores your answers"
- Include: demo video link, GitHub link, example report screenshot, what makes gap detection different

---

## Recurring — Any Day

### [ ] API key rotation / billing watch

- Gemini / Google AI Studio TTS: check usage at [https://aistudio.google.com](https://aistudio.google.com)
- Deepgram: check credits at [https://console.deepgram.com](https://console.deepgram.com)

Free tiers are sufficient for the 10-day build, but keep an eye on Deepgram streaming hours if you run many long voice sessions.

---

## Keys to Add to `.env` (full list)

| Variable | Where to get it | When needed | Status |
|---|---|---|---|
| `GEMINI_API_KEY` | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | Day 1 | Done |
| `GOOGLE_AI_API_KEY` | Same key as above | Day 3 (TTS) | Done |
| `DEEPGRAM_API_KEY` | [console.deepgram.com](https://console.deepgram.com) | Day 3 | Done |
