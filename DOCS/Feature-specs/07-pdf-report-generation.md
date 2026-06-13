# Feature Spec 07 - PDF Report Generation

**Roadmap reference:** Day 7

**Assumption:** Day 7 turns a validated `ReportData` object into a cached PDF file and exposes a backend download endpoint; full frontend report-preview UI remains Day 9 polish unless a minimal internal HTML preview is added for debugging.

---

## 1. Data Fetching

**Concern:** Gather the already-synthesized report content needed to render a PDF without re-running resume parsing, question generation, interview decisions, or scoring directly.

### Inputs

| Source | Data | How it is used |
|---|---|---|
| `synthesize_report(session_id)` | Validated `ReportData` | Source of truth for every score, quote, action item, and feedback section in the PDF |
| Filesystem `reports/` directory | Existing `session_id` PDF, if present | Optional cache to avoid regenerating the same PDF on repeated downloads |
| `backend/templates/report_template.html` | Jinja2 HTML template and CSS | Defines all visible PDF layout and print styling |
| Static assets, optional | Fonts, logo, or simple local assets | Used only if stored locally and referenced through a stable `base_url` |

### Fetch Rules

- Load report content only through `synthesize_report(session_id)`.
- Do not fetch raw resume text for PDF rendering.
- Do not query score rows, transcript rows, or question banks from the renderer; those are Day 6 synthesizer responsibilities.
- Do not let the template recompute scores, category averages, or action-item priority.
- If a cached PDF exists for the same `session_id`, the endpoint may return it directly unless a force-refresh path is explicitly requested for internal testing.
- If rendering fails after synthesis succeeds, surface a PDF rendering error; do not return partial or stale output silently.

### Alignment Constraints

- `session_id` in the URL, `ReportData.session_id`, and generated filename must stay in sync.
- The PDF must represent exactly one interview session.
- The PDF must preserve the same `per_question_feedback` order produced by `ReportData`.
- Exact quotes in `ReportData` must render verbatim. Template filters may escape HTML, but must not summarize, truncate beyond an explicit visual rule, or paraphrase quotes.
- Skipped questions must render as skipped and must not display a numeric score.
- Score colors must be visual only; they must not change the underlying numeric value.

---

## 2. `report_template.html` - `backend/templates/report_template.html`

**Concern:** Render a professional report layout from `ReportData` using plain HTML and CSS suitable for WeasyPrint.

### Template Inputs

| Template variable | Source | Notes |
|---|---|---|
| `report` | `ReportData.model_dump()` or equivalent validated dict | Main content object |
| `generated_at_display` | Renderer formatting helper | Human-readable timestamp derived from `ReportData.generated_at` |
| `score_class` helper | Renderer or Jinja filter | Maps numeric score to `low`, `medium`, or `high` CSS class |
| `score_percent` helper | Renderer or Jinja filter | Converts a 1-10 score to bar width percentage |

### UI Surfaces

| PDF surface | What it previews or pre-fills |
|---|---|
| Cover/header band | Candidate/resume name, session ID, generated date, and overall score |
| Score summary | Overall score plus dimension breakdown bars for relevance, specificity, structure, and communication |
| Category breakdown | Average score, answered count, and skipped count by question category |
| Top moments | Best answer quote, weakest answer quote, and missed opportunity note |
| Action plan | Five prioritized action items, preserving priority order 1 through 5 |
| Per-question feedback | Question text, category, exact answer quote, score or skipped state, strength, improvement area, and first-person rewrite |
| Footer | Page number, product/report label, and lightweight confidentiality note |

### Visual Rules

- Use a restrained professional layout: clear section hierarchy, readable type, and enough whitespace for PDF review.
- Use score bars for overall, dimension, category, and per-question scores where appropriate.
- Use color-coded categories or score state:
  - Low: red tone for scores below 5.0
  - Medium: amber tone for scores from 5.0 through 7.4
  - High: green tone for scores 7.5 and above
- Quote blocks must visually distinguish exact candidate words from coaching notes.
- Suggested rewrites must read as candidate speech, not as a reviewer comment.
- Avoid interactive-only UI patterns; the PDF must stand alone when opened outside the web app.
- Avoid external network assets. Any fonts or images must be local so rendering is deterministic.

### Pagination Rules

- The cover/summary should start on page 1.
- Per-question feedback can span multiple pages.
- Avoid splitting a short question feedback block across pages when possible.
- Long quotes may wrap naturally, but must remain readable and associated with the correct question.
- Page numbers should appear after the first page if WeasyPrint page counters are used.

---

## 3. `render_report_pdf` Service - `backend/report/renderer.py`

**Concern:** Convert validated `ReportData` into a stable PDF file path using Jinja2 and WeasyPrint.

### Public Entry Point

`render_report_pdf(session_id, force_refresh=False) -> Path`

### Mutation: Resolve PDF Path

- **State it manages:** Local filesystem path under `reports/`.
- **Exact API call:** `Path(...).mkdir(parents=True, exist_ok=True)` for the `reports/` directory, then a deterministic path such as `reports/{session_id}.pdf`.
- **Side effect:** Creates the reports directory if missing. Does not navigate, refresh, or redirect.

### Mutation: Return Cached PDF

- **State it manages:** Existing rendered report file for a session.
- **Exact API call:** `Path.exists()` on the resolved PDF path when `force_refresh` is false.
- **Side effect:** Returns the existing PDF path without calling `synthesize_report(session_id)` again. Does not navigate, refresh, or redirect.

### Mutation: Load Report Data

- **State it manages:** Local `ReportData` object for one render operation.
- **Exact API call:** `synthesize_report(session_id)`.
- **Side effect:** May trigger Gemini report synthesis through Day 6 if no cached PDF is used. Does not write the PDF yet.

### Mutation: Render HTML

- **State it manages:** HTML string for one PDF render.
- **Exact API call:** Jinja2 `Environment(loader=FileSystemLoader(template_dir), autoescape=True)`, then `env.get_template("report_template.html")`, then `template.render(...)`.
- **Side effect:** None outside memory. Does not write files, navigate, refresh, or redirect.

### Mutation: Write PDF

- **State it manages:** Final PDF bytes on disk.
- **Exact API call:** WeasyPrint `HTML(string=rendered_html, base_url=str(template_dir)).write_pdf(target=pdf_path)`.
- **Side effect:** Writes or overwrites the PDF at the resolved path. Does not navigate, refresh, or redirect.

### Mutation: Validate Output

- **State it manages:** Rendered file metadata.
- **Exact API call:** `Path.exists()` and `Path.stat().st_size`.
- **Side effect:** Raises a rendering error if the PDF is missing or empty. Does not navigate, refresh, or redirect.

### Error Handling

- If `synthesize_report(session_id)` fails, propagate a report-not-ready or synthesis error to the caller.
- If the Jinja2 template is missing or references an invalid field, raise a render error; do not return an empty PDF.
- If WeasyPrint fails because of invalid HTML/CSS/assets, raise a render error with enough context for logs.
- If the output path exists but is zero bytes, treat it as failed output and regenerate or raise.
- Do not swallow rendering exceptions inside the service; the API layer should translate them into HTTP responses.

---

## 4. PDF Download API - `backend/api/report.py`

**Concern:** Provide a user-facing HTTP boundary for downloading the rendered PDF.

### Route

`GET /reports/{session_id}/download`

### Mutation: Generate Or Reuse PDF

- **State it manages:** Cached PDF file for the requested session.
- **Exact API call:** `render_report_pdf(session_id)`.
- **Side effect:** Creates a PDF file under `reports/` if one does not already exist. Does not navigate on the backend.

### Mutation: Return Download Response

- **State it manages:** HTTP response metadata.
- **Exact API call:** FastAPI/Starlette `FileResponse(path, media_type="application/pdf", filename=<download_name>)`.
- **Side effect:** Browser receives a downloadable PDF response. The browser may show a save/open dialog depending on client settings; backend does not redirect.

### Response Rules

- Successful response media type must be `application/pdf`.
- Download filename should be stable and human-readable, such as `interview-report-{session_id}.pdf`.
- If `session_id` is unknown or report inputs are missing, return a 404 or 409-style response with a clear message.
- If PDF rendering fails, return a 500-style response and log the failure.
- The endpoint must not return raw `ReportData` JSON; Day 6 already covers the JSON object.

### Alignment Constraints

- The route `session_id` must be passed unchanged into `render_report_pdf(session_id)`.
- The response filename must not allow path traversal. It should be constructed from a sanitized session ID or fixed prefix.
- The endpoint must not expose arbitrary files from `reports/`; it only serves the file path returned by the renderer for that `session_id`.

---

## 5. FastAPI Wiring - `backend/main.py`

**Concern:** Register the report router without disturbing the existing interview WebSocket route.

### Mutation: Include Report Router

- **State it manages:** FastAPI route table.
- **Exact API call:** `app.include_router(report_router)` where `report_router` comes from `backend.api.report`.
- **Side effect:** Adds the PDF download route to the running API. Does not navigate, refresh, or redirect.

### Route Alignment

- Existing `ws://localhost:8000/ws/interview/{session_id}` behavior must remain unchanged.
- The report route should be under `/reports/...` to match the filesystem artifact and avoid colliding with `/ws/interview/...`.
- Health check behavior must remain unchanged.

---

## 6. Optional HTML Debug Preview

**Concern:** Make template development easier without creating the full frontend report UI ahead of Day 9.

### Route, If Added

`GET /reports/{session_id}/preview`

### Mutation: Render HTML Preview

- **State it manages:** Temporary HTML string generated from `ReportData`.
- **Exact API call:** Same Jinja2 environment and template rendering path used by `render_report_pdf`, but without calling WeasyPrint.
- **Side effect:** Returns an HTML response for local inspection. Does not write a PDF unless the implementor deliberately shares the renderer path.

### UI Surface

| Surface | What it previews or pre-fills |
|---|---|
| Browser HTML preview | Same template content as the PDF: score summary, top moments, action items, and per-question feedback |

### Rules

- This route is optional and should be clearly treated as internal/debug-only.
- The PDF renderer remains the source of truth for Day 7 completion.
- If added, the preview must use the exact same template data shape as the PDF renderer.

---

## 7. Filesystem Persistence

**Concern:** Keep generated PDFs predictable, local, and easy to serve.

### Directory

`reports/`

### File Naming

`{session_id}.pdf`

### Mutation: Persist Rendered PDF

- **State it manages:** One generated PDF artifact per session.
- **Exact API call:** WeasyPrint `write_pdf(target=pdf_path)` through `render_report_pdf`.
- **Side effect:** Writes a PDF file to `reports/`.

### Persistence Rules

- Do not store PDFs in SQLite.
- Do not store raw HTML in SQLite.
- If future caching metadata is needed, add it later with an explicit reports table; Day 7 only needs the file artifact.
- Regeneration with `force_refresh=True` may overwrite the session PDF.
- Tests should use a temporary reports directory or monkeypatch the renderer path so they do not write permanent artifacts.

---

## 8. Template Data Mapping

**Concern:** Ensure every visible PDF section maps directly to `ReportData` fields and needs no extra interpretation.

### Mapping Rules

| `ReportData` field | PDF section |
|---|---|
| `session_id` | Header/footer metadata and filename derivation |
| `resume_name` | Report title/header |
| `generated_at` | Generated date display |
| `overall_score` | Hero score and summary bar |
| `dimension_breakdown` | Dimension score bars |
| `category_breakdown` | Category score table or cards |
| `top_moments` | Top moments section |
| `action_items` | Prioritized action plan |
| `per_question_feedback` | Detailed feedback section |

### Alignment Constraints

- `category_breakdown` must render categories using names from `ReportData`; the template must not hardcode that all categories are present.
- Skipped feedback rows must show a skipped state and suppress score bars.
- `None` fields must render as absent or skipped-state text, never as the literal string `None`.
- Rewrites must remain tied to their original `question_id`.
- Action items must render sorted by `priority`; if `ReportData` already arrives sorted, preserve that order.

---

## 9. Tests and Fixtures

**Concern:** Verify PDF generation without requiring a live voice session or network-backed Gemini call.

### Test Inputs

- A valid mock `ReportData` with:
  - At least five feedback rows across multiple categories
  - One skipped question
  - Long enough quotes to test wrapping
  - Five action items
- A fixture where `render_report_pdf` receives an unknown session ID and `synthesize_report` raises.
- A fixture where WeasyPrint returns or writes an empty PDF file.

### Required Checks

- Renderer writes a non-empty `.pdf` file.
- Renderer calls `synthesize_report(session_id)` when no cached file exists.
- Renderer does not call `synthesize_report(session_id)` when cached file exists and `force_refresh=False`.
- `force_refresh=True` regenerates the PDF.
- Template output includes the resume name, overall score, at least one exact quote, and all five action item titles.
- Skipped feedback renders without a numeric score.
- Download endpoint returns `application/pdf`.
- Download endpoint returns a file named like `interview-report-{session_id}.pdf`.
- Missing report inputs produce a clear HTTP error instead of a blank PDF.

---

## 10. Check When Done

- [ ] `backend/templates/report_template.html` exists and renders all `ReportData` sections: header, score summary, category breakdown, top moments, five action items, and per-question feedback.
- [ ] `backend/report/renderer.py` exposes `render_report_pdf(session_id, force_refresh=False) -> Path`.
- [ ] Renderer loads report content through `synthesize_report(session_id)` and does not query raw scores/transcripts directly.
- [ ] Renderer uses Jinja2 `FileSystemLoader`, `Environment.get_template(...)`, and `template.render(...)` for HTML generation.
- [ ] Renderer uses WeasyPrint `HTML(string=..., base_url=...).write_pdf(target=...)` for PDF generation.
- [ ] Generated PDFs are written under `reports/` using a deterministic session-based filename.
- [ ] Cached PDFs are reused on repeated downloads unless force refresh is requested.
- [ ] Generated PDF file is non-empty and opens in a standard PDF reader.
- [ ] Exact transcript quotes from `ReportData` appear in the PDF.
- [ ] Skipped questions appear as skipped and do not show numeric scores.
- [ ] Score bars and red/amber/green score states render correctly.
- [ ] `backend/api/report.py` exposes `GET /reports/{session_id}/download`.
- [ ] The download endpoint returns `FileResponse(..., media_type="application/pdf", filename=...)`.
- [ ] `backend/main.py` includes the report router without breaking the interview WebSocket route.
- [ ] Renderer tests pass using mock `ReportData`, including cache reuse and force-refresh behavior.
- [ ] API tests confirm the download route returns a PDF response for a valid session and a clear error for missing inputs.
- [ ] Full flow works locally once live data exists: upload resume -> voice interview -> scoring -> report synthesis -> PDF download.
