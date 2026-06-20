import logging
from datetime import datetime
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
    WEASYPRINT_ERROR = None
except Exception as e:
    WEASYPRINT_AVAILABLE = False
    WEASYPRINT_ERROR = e

from backend.report.synthesizer import synthesize_report

logger = logging.getLogger(__name__)

# Base directories
BACKEND_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BACKEND_DIR / "templates"
REPORTS_DIR = BACKEND_DIR.parent / "reports"


class PDFRenderingError(RuntimeError):
    """Raised when HTML rendering or PDF writing fails."""


def score_class(score: float | int | None) -> str:
    if score is None:
        return "low"
    score_val = float(score)
    if score_val < 5.0:
        return "low"
    elif score_val < 7.5:
        return "medium"
    else:
        return "high"


def score_percent(score: float | int | None) -> float:
    if score is None:
        return 0.0
    return float(score) * 10.0


def render_report_pdf(session_id: str, force_refresh: bool = False) -> Path:
    """
    Renders a validated ReportData object into a PDF file on the local filesystem.
    Uses caching by default unless force_refresh is True.
    """
    # Deterministic file path under reports/
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = REPORTS_DIR / f"{session_id}.pdf"

    # Return cached PDF if present and valid
    if not force_refresh and pdf_path.exists() and pdf_path.stat().st_size > 0:
        logger.info(f"Returning cached PDF report for session {session_id}")
        return pdf_path

    logger.info(f"Generating new PDF report for session {session_id}")
    
    # 1. Load report data (raises ReportSynthesisError if inputs or validation fails)
    report = synthesize_report(session_id)

    # 2. Format displays and CSS classes
    try:
        # ISO format to human readable, e.g. "2026-06-13T18:38:48.000Z" -> "June 13, 2026 at 06:38 PM UTC"
        # We replace 'Z' if present to make it fromisoformat-compatible in standard python datetime
        iso_str = report.generated_at.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso_str)
        generated_at_display = dt.strftime("%B %d, %Y at %I:%M %p UTC")
    except Exception as e:
        logger.warning(f"Could not parse generated_at date {report.generated_at}: {e}")
        generated_at_display = report.generated_at

    overall_class = score_class(report.overall_score)

    # 3. Setup Jinja2 Environment and Render
    try:
        if not TEMPLATES_DIR.exists():
            raise PDFRenderingError(f"Templates directory not found: {TEMPLATES_DIR}")

        env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
        template = env.get_template("report_template.html")
        
        rendered_html = template.render(
            report=report.model_dump(),
            generated_at_display=generated_at_display,
            overall_class=overall_class,
            score_class=score_class,
            score_percent=score_percent
        )
    except Exception as e:
        logger.error(f"Jinja2 rendering failed for session {session_id}: {e}")
        raise PDFRenderingError(f"HTML rendering failed: {e}") from e

    # 4. Generate PDF using WeasyPrint
    if not WEASYPRINT_AVAILABLE:
        raise PDFRenderingError(
            "WeasyPrint library dependencies (GTK3 Runtime) are missing. Please install GTK3 "
            f"on Windows to enable PDF generation. Error: {WEASYPRINT_ERROR}"
        )

    try:
        HTML(string=rendered_html, base_url=str(TEMPLATES_DIR)).write_pdf(target=pdf_path)
    except Exception as e:
        logger.error(f"WeasyPrint PDF generation failed for session {session_id}: {e}")
        raise PDFRenderingError(f"PDF writing failed: {e}") from e

    # 5. Validate output
    if not pdf_path.exists() or pdf_path.stat().st_size == 0:
        if pdf_path.exists():
            try:
                pdf_path.unlink()
            except Exception:
                pass
        raise PDFRenderingError("Rendered PDF is empty or missing after generation.")

    logger.info(f"Successfully wrote PDF report to {pdf_path}")
    return pdf_path
