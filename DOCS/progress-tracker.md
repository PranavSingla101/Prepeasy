# Progress Tracker

Update this file after every meaningful implementation change.

## Current Phase

- In Progress

## Current Goal

- Day 1 — Resume Parser: PDF → raw text → structured JSON → SQLite

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

## In Progress

- Awaiting `GEMINI_API_KEY` to run live verification against `DOCS/Pranav-GTM-intern.pdf`

## Next Up

- Set `GEMINI_API_KEY` in `.env` and run:
  ```
  cd c:\Users\LENOVO\Documents\project\Interview-Agent
  Interv\Scripts\python.exe -m backend.parse_resume DOCS/Pranav-GTM-intern.pdf
  ```
- Verify all checklist items in `DOCS/Feature-specs/01-resume-parser.md`
- Day 2 — Question Generator (gap_analysis → probing interview questions)

## Open Questions

- None at this time

## Architecture Decisions

- **Gemini 2.5 Flash** used as LLM (not Claude) — specified in `DOCS/Tech-stack.md`
- **SQLite DB** stored at `data/interviews.db` (project root), gitignored
- `response_mime_type="application/json"` used in Gemini call to enforce JSON output natively
- Prompt template lives at `backend/prompts/extraction_v1.txt` — never hardcoded in Python
- `ResumeData.model_validate()` used after JSON parse — if validation fails, fix the prompt, not the schema
- `duration_months` has a `coerce_duration` validator to handle LLM returning strings instead of ints

## Session Notes

- Virtual env: `Interv/` — activate with `Interv\Scripts\activate`
- All required packages already installed: pdfplumber, PyMuPDF, google-genai, python-dotenv, pydantic, sqlite3 (stdlib)
- Run parser: `python -m backend.parse_resume <path/to/resume.pdf>` from project root
