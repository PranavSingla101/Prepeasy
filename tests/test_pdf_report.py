import sys
from unittest.mock import MagicMock

class MockHTML:
    def __init__(self, string=None, base_url=None):
        self.string = string
        self.base_url = base_url

    def write_pdf(self, target):
        from pathlib import Path
        Path(target).write_bytes(b"%PDF-mock-bytes")

mock_weasyprint = MagicMock()
mock_weasyprint.HTML = MockHTML
sys.modules["weasyprint"] = mock_weasyprint

import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.report.renderer import render_report_pdf, PDFRenderingError
from backend.report.synthesizer import ReportSynthesisError
from backend.schemas.report import ReportData


class PDFReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = TemporaryDirectory(ignore_cleanup_errors=True)
        self.reports_dir_patch = patch("backend.report.renderer.REPORTS_DIR", Path(self.tmpdir.name) / "reports")
        self.mock_reports_dir = self.reports_dir_patch.start()
        
        # Base mock data for ReportData
        self.mock_report_dict = {
            "session_id": "test-session",
            "resume_name": "Jane Doe",
            "generated_at": "2026-06-13T18:38:48.000Z",
            "overall_score": 8.2,
            "dimension_breakdown": {
                "relevance": 8.0,
                "specificity": 8.5,
                "structure": 8.0,
                "communication": 8.5
            },
            "category_breakdown": [
                {
                    "category": "behavioral",
                    "average_score": 8.5,
                    "answered_count": 2,
                    "skipped_count": 0
                },
                {
                    "category": "technical",
                    "average_score": 7.8,
                    "answered_count": 2,
                    "skipped_count": 0
                }
            ],
            "top_moments": {
                "best_answer_question_id": "behavioral_01",
                "best_answer_quote": "I reduced pipeline latency by 45 percent.",
                "weakest_answer_question_id": "technical_01",
                "weakest_answer_quote": "I just ran the script.",
                "missed_opportunity_question_id": "technical_02",
                "missed_opportunity_summary": "Should have mentioned memory profiling details."
            },
            "per_question_feedback": [
                {
                    "question_id": "behavioral_01",
                    "category": "behavioral",
                    "question_text": "Tell me about a time you optimized a pipeline.",
                    "answer_quote": "I reduced pipeline latency by 45 percent.",
                    "score": 8.5,
                    "strength": "Quantified result",
                    "improvement_area": "Explain tools used",
                    "suggested_rewrite": "I reduced the deployment pipeline latency by 45 percent using parallel workers.",
                    "skipped": False
                },
                {
                    "question_id": "technical_01",
                    "category": "technical",
                    "question_text": "How do you run docker compose?",
                    "answer_quote": "I just ran the script.",
                    "score": 4.5,
                    "strength": "Answered the prompt",
                    "improvement_area": "Lacked specific configurations",
                    "suggested_rewrite": "I configured the services using docker-compose up with custom network profiles.",
                    "skipped": False
                },
                {
                    "question_id": "technical_02",
                    "category": "technical",
                    "question_text": "Did you analyze performance?",
                    "answer_quote": None,
                    "score": None,
                    "strength": None,
                    "improvement_area": "Skipped question",
                    "suggested_rewrite": None,
                    "skipped": True
                }
            ],
            "action_items": [
                {
                    "priority": 1,
                    "title": "Use specific technical details",
                    "why_it_matters": "Shows deeper mastery.",
                    "example_from_session": "I just ran the script.",
                    "practice_instruction": "Practice explaining configurations."
                },
                {
                    "priority": 2,
                    "title": "Quantify outcomes always",
                    "why_it_matters": "Business alignment.",
                    "example_from_session": "I reduced pipeline latency by 45 percent.",
                    "practice_instruction": "Keep metrics handy."
                },
                {
                    "priority": 3,
                    "title": "Prepare transitions",
                    "why_it_matters": "Shows logical reasoning.",
                    "example_from_session": "I reduced pipeline latency by 45 percent.",
                    "practice_instruction": "Explain why steps were taken."
                },
                {
                    "priority": 4,
                    "title": "Explain trade-offs",
                    "why_it_matters": "Shows maturity.",
                    "example_from_session": "I reduced pipeline latency by 45 percent.",
                    "practice_instruction": "Practice listing pros and cons."
                },
                {
                    "priority": 5,
                    "title": "Explain team context",
                    "why_it_matters": "Shows collaboration.",
                    "example_from_session": "I reduced pipeline latency by 45 percent.",
                    "practice_instruction": "Mention who you aligned with."
                }
            ]
        }
        
        # Validated ReportData model
        self.mock_report_data = ReportData.model_validate(
            self.mock_report_dict,
            context={
                "question_ids": {"behavioral_01", "technical_01", "technical_02"},
                "allowed_quotes": {
                    "I reduced pipeline latency by 45 percent.",
                    "I just ran the script.",
                },
                "feedback_order": ["behavioral_01", "technical_01", "technical_02"],
                "expected_feedback": {
                    "behavioral_01": {
                        "category": "behavioral",
                        "question_text": "Tell me about a time you optimized a pipeline.",
                        "score": 8.5,
                        "skipped": False
                    },
                    "technical_01": {
                        "category": "technical",
                        "question_text": "How do you run docker compose?",
                        "score": 4.5,
                        "skipped": False
                    },
                    "technical_02": {
                        "category": "technical",
                        "question_text": "Did you analyze performance?",
                        "score": None,
                        "skipped": True
                    }
                }
            }
        )

    def tearDown(self) -> None:
        self.reports_dir_patch.stop()
        self.tmpdir.cleanup()

    @patch("backend.report.renderer.synthesize_report")
    def test_renderer_generates_valid_pdf(self, mock_synth: MagicMock) -> None:
        mock_synth.return_value = self.mock_report_data
        
        pdf_path = render_report_pdf("test-session")
        self.assertTrue(pdf_path.exists())
        self.assertGreater(pdf_path.stat().st_size, 0)
        mock_synth.assert_called_once_with("test-session")

    @patch("backend.report.renderer.synthesize_report")
    def test_renderer_cache_behavior(self, mock_synth: MagicMock) -> None:
        mock_synth.return_value = self.mock_report_data
        
        # First call: actually generates
        pdf_path_1 = render_report_pdf("test-session")
        self.assertTrue(pdf_path_1.exists())
        self.assertEqual(mock_synth.call_count, 1)
        
        # Second call with force_refresh=False: uses cache
        pdf_path_2 = render_report_pdf("test-session", force_refresh=False)
        self.assertEqual(pdf_path_1, pdf_path_2)
        self.assertEqual(mock_synth.call_count, 1)
        
        # Third call with force_refresh=True: regenerates
        pdf_path_3 = render_report_pdf("test-session", force_refresh=True)
        self.assertEqual(pdf_path_1, pdf_path_3)
        self.assertEqual(mock_synth.call_count, 2)

    @patch("backend.report.renderer.synthesize_report")
    def test_rendering_failure_raises_exception(self, mock_synth: MagicMock) -> None:
        # If synthesizer fails
        mock_synth.side_effect = ReportSynthesisError("Synthesis failed")
        
        with self.assertRaises(ReportSynthesisError):
            render_report_pdf("test-session")
            
        # If template is missing or WeasyPrint fails
        mock_synth.side_effect = None
        mock_synth.return_value = self.mock_report_data
        
        with patch("backend.report.renderer.HTML") as mock_html:
            mock_html.side_effect = Exception("WeasyPrint crash")
            with self.assertRaises(PDFRenderingError):
                render_report_pdf("test-session", force_refresh=True)

    @patch("backend.api.report.synthesize_report")
    @patch("backend.api.report.render_report_pdf")
    def test_api_download_route(self, mock_render: MagicMock, mock_synth: MagicMock) -> None:
        # Setup mock file response
        fake_pdf = Path(self.tmpdir.name) / "reports" / "test-session.pdf"
        fake_pdf.parent.mkdir(parents=True, exist_ok=True)
        fake_pdf.write_text("fake pdf bytes")
        mock_render.return_value = fake_pdf
        
        client = TestClient(app)
        
        # Valid request
        response = client.get("/reports/test-session/download")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertIn("attachment", response.headers["content-disposition"])
        self.assertIn("interview-report-test-session.pdf", response.headers["content-disposition"])
        self.assertEqual(response.content, b"fake pdf bytes")
        
        # Path traversal prevention / invalid session ID format
        response_traversal = client.get("/reports/..%2Fsession/download")
        self.assertIn(response_traversal.status_code, [400, 404])
        
        response_invalid = client.get("/reports/test-session@123/download")
        self.assertEqual(response_invalid.status_code, 400)
        self.assertIn("Invalid session ID format", response_invalid.json()["detail"])

    @patch("backend.api.report.synthesize_report")
    def test_api_preview_route(self, mock_synth: MagicMock) -> None:
        mock_synth.return_value = self.mock_report_data
        
        client = TestClient(app)
        response = client.get("/reports/test-session/preview")
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/html; charset=utf-8")
        
        # Check that specific content fields exist in the HTML response
        html_content = response.text
        self.assertIn("Jane Doe", html_content)
        self.assertIn("8.2", html_content)
        self.assertIn("I reduced pipeline latency by 45 percent.", html_content)
        self.assertIn("Use specific technical details", html_content)
        self.assertIn("SKIPPED", html_content)
        self.assertIn("Did you analyze performance?", html_content)

    @patch("backend.api.report.render_report_pdf")
    def test_api_not_found_handling(self, mock_render: MagicMock) -> None:
        mock_render.side_effect = KeyError("Session not found")
        
        client = TestClient(app)
        response = client.get("/reports/missing-session/download")
        self.assertEqual(response.status_code, 404)
        self.assertIn("Session or question bank not found", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
