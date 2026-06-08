# Day 1 — Resume Parser

**Objective:** Take any PDF resume and produce a clean, structured JSON object that every other part of the system will use. After this step, no other layer ever reads raw PDF text again.

---

## What We're Building

Two things:

1. **Text extractor** — pulls raw text out of a PDF file
2. **LLM structured extractor** — sends that raw text to Claude and gets back a validated JSON object

---

## File Structure to Create

```
backend/
  parser/
    __init__.py
    extractor.py       ← PDF → raw text
    structured.py      ← raw text → JSON via LLM
  prompts/
    extraction_v1.txt  ← the extraction prompt
  schemas/
    __init__.py
    resume.py          ← ResumeData Pydantic model
  db/
    __init__.py
    session.py         ← SQLite setup and save functions
  parse_resume.py      ← CLI entry point
```

---

## Step 1 — PDF Text Extraction (`extractor.py`)

Primary tool: `pdfplumber`
Fallback: `pymupdf` (for scanned or image-based PDFs where pdfplumber returns empty)

Logic:
- Try pdfplumber first
- If the extracted text is empty or under 100 characters, fall back to pymupdf
- Return a single string of all page text joined by newlines
- Strip excessive whitespace and blank lines

---

## Step 2 — LLM Structured Extraction (`structured.py`)

Send the raw text to Claude with the extraction prompt.

The output JSON must contain:

```
name
contact (email, phone, linkedin — optional)
skills
  languages      list of strings
  frameworks     list of strings
  tools          list of strings
education
  degree
  institution
  year
experience (array)
  company
  role
  duration_months
  has_metrics         boolean — does this role mention any numbers/results?
  vague_claims        list — bullets that are vague ("improved performance", "worked on X")
gap_analysis          list of strings — the key differentiator
  examples:
  - "Only 4 months at Company X — short tenure, will be probed"
  - "No metrics on any role — claims exist but no numbers to back them"
  - "Claims Python expertise but no Python project listed"
  - "2-month gap between Job A and Job B with no explanation"
  - "'Familiar with machine learning' — vague, no project evidence"
```

**The `gap_analysis` field is the most important field in the whole system.** It drives the gap-probing questions in Day 2. Be strict: if something on the resume looks weak, short, vague, or inconsistent — it goes in `gap_analysis`.

Prompt lives at `backend/prompts/extraction_v1.txt`. Never hardcode the prompt in the function.

Enforce JSON output — instruct the model to return only valid JSON with no prose around it.

---

## Step 3.5 — Pydantic Validation (`schemas/resume.py`)

Define a `ResumeData` Pydantic model that mirrors the JSON schema above. After LLM extraction, validate the output through this model before anything else touches it.

- If validation fails, fix the prompt — not the schema
- Every downstream layer receives a validated `ResumeData` object, never raw JSON strings

---

## Step 4 — Store to SQLite (`db/session.py`)

- Create a `resumes` table: `(id, filename, raw_text, structured_json, created_at)`
- After a successful extraction, insert a row
- Return the `resume_id` — this is the key used by every downstream layer

Schema:

```
resumes
  id             TEXT  (UUID)
  filename       TEXT
  raw_text       TEXT
  structured_json TEXT  (stored as JSON string)
  created_at     TEXT  (ISO timestamp)
```

---

## Step 5 — CLI Entry Point (`parse_resume.py`)

Wire a CLI entry point at `backend/parse_resume.py` that:
- Accepts a PDF file path as an argument
- Runs extraction → Pydantic validation → SQLite storage
- Prints the resulting `resume_id` and `gap_analysis` to stdout

---

## Sample PDF

`DOCS/Resume_sample/Pranav-GTM-intern.pdf` — use this as the primary test file throughout Day 1.

- Run every step against this file first


---

## Verification Checklist

Run the parser on `Pranav-GTM-intern.pdf` first, then on at least 3–4 more resumes of varying formats (junior, mid-level, PM, non-English if available).

| Check | Pass condition |
|---|---|
| PDF loads without error | No exception thrown |
| Raw text is non-empty | More than 200 characters extracted |
| Fallback triggers correctly | PyMuPDF used when pdfplumber returns empty |
| JSON output is valid | `json.loads()` succeeds |
| All required fields present | name, skills, experience, gap_analysis all exist |
| `gap_analysis` is populated | At least 1 item for any realistic resume |
| `has_metrics` is accurate | True only when role contains actual numbers |
| `vague_claims` are real | Pulls weak bullets, not strong ones |
| SQLite row is created | Query `resumes` table — row exists with correct resume_id |
| Pydantic validation passes | `ResumeData(**output)` succeeds without errors |
| Under 10 seconds total | Time the full flow from file path to stored JSON |

---

## Edge Cases to Handle

- Password-protected PDF → catch the exception, return a clear error message
- PDF with only images (scanned) → pymupdf fallback handles this
- Very short PDF (1-page, sparse) → `gap_analysis` may be short, that's valid
- Non-English resume → extraction still runs, gap analysis may be less precise, acceptable for now
- Corrupt PDF → catch and return error, do not crash

---

## Definition of Done

Upload any PDF resume → get a valid structured JSON object with `gap_analysis` populated, stored in SQLite, in under 10 seconds.

If you read the `gap_analysis` array out loud and it sounds like real observations a human recruiter would make — Day 1 is done.
