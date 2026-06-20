import logging
import re
from datetime import datetime
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from jinja2 import Environment, FileSystemLoader

from backend.report.renderer import render_report_pdf, PDFRenderingError, score_class, score_percent, TEMPLATES_DIR
from backend.report.synthesizer import ReportSynthesisError, synthesize_report

logger = logging.getLogger(__name__)

router = APIRouter()


def sanitize_session_id(session_id: str) -> str:
    """Sanitizes the session ID to prevent path traversal or invalid character injections."""
    if not re.match(r"^[a-zA-Z0-9_\-]+$", session_id):
        raise HTTPException(status_code=400, detail="Invalid session ID format")
    return session_id


@router.get("/reports/{session_id}/download")
def download_report_pdf(session_id: str):
    """
    Renders and downloads the PDF report for the given session_id.
    Returns a FileResponse with appropriate headers.
    """
    session_id = sanitize_session_id(session_id)
    try:
        pdf_path = render_report_pdf(session_id)
        
        # Sanitize download filename to avoid any path injection in headers
        download_name = f"interview-report-{session_id}.pdf"
        
        return FileResponse(
            path=pdf_path,
            media_type="application/pdf",
            filename=download_name
        )
    except KeyError as exc:
        logger.warning(f"Session not found during PDF generation: {session_id}")
        raise HTTPException(status_code=404, detail="Session or question bank not found")
    except ReportSynthesisError as exc:
        logger.warning(f"Synthesis failed during PDF generation: {session_id} - {exc}")
        raise HTTPException(status_code=409, detail=f"Report cannot be synthesized: {exc}")
    except PDFRenderingError as exc:
        logger.error(f"PDF rendering failed for session {session_id}: {exc}")
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {exc}")
    except Exception as exc:
        logger.error(f"Unexpected error rendering PDF for session {session_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error during PDF generation")


@router.get("/reports/{session_id}/preview", response_class=HTMLResponse)
def preview_report_html(session_id: str):
    """
    Renders and displays the HTML report preview for testing and template verification.
    """
    session_id = sanitize_session_id(session_id)
    try:
        report = synthesize_report(session_id)
        
        # Format display dates
        try:
            iso_str = report.generated_at.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso_str)
            generated_at_display = dt.strftime("%B %d, %Y at %I:%M %p UTC")
        except Exception:
            generated_at_display = report.generated_at

        overall_class = score_class(report.overall_score)

        if not TEMPLATES_DIR.exists():
            raise HTTPException(status_code=500, detail="Templates directory not found")

        env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
        template = env.get_template("report_template.html")
        
        rendered_html = template.render(
            report=report.model_dump(),
            generated_at_display=generated_at_display,
            overall_class=overall_class,
            score_class=score_class,
            score_percent=score_percent
        )
        return HTMLResponse(content=rendered_html)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session or question bank not found")
    except ReportSynthesisError as exc:
        raise HTTPException(status_code=409, detail=f"Report cannot be synthesized: {exc}")
    except Exception as exc:
        logger.error(f"Unexpected error rendering HTML preview for session {session_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Preview generation failed: {exc}")
