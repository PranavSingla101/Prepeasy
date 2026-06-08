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

## Day 2 — Question Bank (next)

### [ ] 4. Manually read the generated question bank

After the question generator is built, run it and read every question. Ask yourself:
- Does each behavioral question reference a specific resume bullet?
- Does each gap-probing question target something real from `gap_analysis`?
- Do any questions sound generic or copy-pasted?

This is a judgment call only you can make — Claude can generate, but you must approve quality.

---

## Day 3 — Voice Pipeline

### [ ] 5. Sign up for Deepgram and get an API key

- URL: [https://console.deepgram.com](https://console.deepgram.com)
- Free tier: $200 credit (~430 hours of streaming)
- Add to `.env`: `DEEPGRAM_API_KEY=...`

### [ ] 6. Sign up for Cartesia and get an API key

- URL: [https://play.cartesia.ai](https://play.cartesia.ai)
- Free tier: 10,000 credits
- Add to `.env`: `CARTESIA_API_KEY=...`

### [ ] 7. Run a live 5-question voice session with yourself

After Day 3 is built, you must physically speak into a microphone and do the session. Verify:
- The agent's voice sounds natural
- Transitions between questions are smooth
- Transcripts are stored per answer in SQLite

No automated test can replace this — you have to sit through it.

---

## Day 4 — Adaptive Follow-ups

### [ ] 8. Test follow-up logic with intentionally weak and strong answers

Give the agent a deliberately vague answer (e.g., "I just kind of helped the team") and verify it triggers `follow_up_if_vague`. Then give a strong, specific answer and verify it either probes deeper or moves on. You must do this manually — it requires natural language judgment.

---

## Day 5 — Scoring

### [ ] 9. Run a full 20-minute session and check SQLite scores

After session ends, open the DB and confirm a score row exists for every answer:

```powershell
Interv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect('data/interviews.db'); print(c.execute('SELECT * FROM scores').fetchall())"
```

---

## Day 6 — Report Synthesis

### [ ] 10. Read the generated report JSON critically

Check every `action_items` entry — they must reference specific things you said, not generic advice. If any item says something like "be more specific" without quoting you, the synthesis prompt needs tuning. This requires reading the output yourself.

---

## Day 7 — PDF Report

### [ ] 11. Visual QA the PDF on mobile and desktop

Open the generated PDF on your phone and on a laptop. Check:
- Score bars render correctly
- Quote blocks don't overflow
- Fonts and layout look professional
- Looks good enough to screenshot and share

---

## Day 8 — Session History

### [ ] 12. Run 3 sessions and verify score trend is accurate

Manually run 3 interview sessions. After each, check that the trend data in the UI or PDF reflects the real scores from SQLite — not dummy/stale data.

---

## Day 9 — JD Targeting

### [ ] 13. Paste a real job description and verify tailored questions

Find a real JD (LinkedIn, Greenhouse, etc.). Paste it into the upload page. Read the generated question bank — at least a few questions should be role-specific and wouldn't exist without the JD.

---

## Day 10 — Demo & Release

### [ ] 14. Record a 3-minute Loom demo video

Script:
- 0:00–0:30 — Upload your resume, show the structured JSON / gap analysis output
- 0:30–2:00 — Run a 5-question voice session, show the live transcript
- 2:00–3:00 — Open the PDF report, zoom into a quote-anchored feedback block

### [ ] 15. Write the README

Must include: what it is, architecture diagram (copy from `DOCS/Project-info-detailed.md`), quick setup instructions, example report screenshot.

### [ ] 16. Push to GitHub

```bash
git init
git add .
git commit -m "initial release"
gh repo create interview-agent --public
git push -u origin main
```

Verify the repo is public and someone else can clone + run it in under 10 minutes.

### [ ] 17. Write and publish the launch post

400-word post for dev.to and/or LinkedIn:
- Title: "I built a voice interview coach that reads your resume and scores your answers"
- Include: demo video link, GitHub link, example report screenshot, what makes gap detection different

---

## Recurring — Any Day

### [ ] API key rotation / billing watch

- Gemini: check usage at [https://aistudio.google.com](https://aistudio.google.com)
- Deepgram: check credits at [https://console.deepgram.com](https://console.deepgram.com)
- Cartesia: check credits at [https://play.cartesia.ai](https://play.cartesia.ai)

Free tiers are sufficient for the 10-day build, but keep an eye on Deepgram streaming hours if you run many long voice sessions.

---

## Keys to Add to `.env` (full list)

| Variable | Where to get it | When needed |
|---|---|---|
| `GEMINI_API_KEY` | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | Day 1 — NOW |
| `DEEPGRAM_API_KEY` | [console.deepgram.com](https://console.deepgram.com) | Day 3 |
| `CARTESIA_API_KEY` | [play.cartesia.ai](https://play.cartesia.ai) | Day 3 |
