import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.db import session as db_session
from backend.report.synthesizer import ReportSynthesisError, synthesize_report
from backend.schemas.questions import QuestionBank
from backend.schemas.scoring import ScoreResult
from backend.schemas.session import TranscriptEntry


def _question(category: str, idx: int) -> dict:
    suffix = f"{idx:02d}"
    return {
        "id": f"{category}_{suffix}",
        "category": category,
        "text": f"{category} question {suffix}?",
        "source_ref": "gap_1" if category == "gap_probing" else "source",
        "follow_up_vague": "Can you give me a concrete example?",
        "follow_up_strong": "What tradeoff did you consider?",
    }


def _bank(session_id: str = "session-1") -> QuestionBank:
    questions = []
    for category, count in {
        "behavioral": 10,
        "technical": 8,
        "gap_probing": 5,
        "situational": 3,
        "closing": 2,
    }.items():
        for idx in range(1, count + 1):
            q = _question(category, idx)
            if category == "closing":
                q["source_ref"] = ""
            questions.append(q)
    return QuestionBank.model_validate({
        "session_id": session_id,
        "resume_name": "Ada Candidate",
        "questions": questions,
    })


def _score(question_id: str, overall_seed: int, skipped: bool = False) -> ScoreResult:
    if skipped:
        return ScoreResult.model_validate({
            "question_id": question_id,
            "skipped": True,
            "relevance": None,
            "specificity": None,
            "structure": None,
            "communication": None,
            "strongest_moment": None,
            "weakest_moment": None,
            "suggested_rewrite": None,
        })
    return ScoreResult.model_validate({
        "question_id": question_id,
        "skipped": False,
        "relevance": overall_seed,
        "specificity": overall_seed,
        "structure": overall_seed,
        "communication": overall_seed,
        "strongest_moment": f"Strong moment for {question_id}.",
        "weakest_moment": f"Weak moment for {question_id}.",
        "suggested_rewrite": f"I would answer {question_id} with clearer impact.",
    })


class ReportSynthesisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_db_path = db_session._DB_PATH
        self.tmpdir = TemporaryDirectory(ignore_cleanup_errors=True)
        db_session._DB_PATH = Path(self.tmpdir.name) / "report.db"

    def tearDown(self) -> None:
        db_session._DB_PATH = self.original_db_path
        self.tmpdir.cleanup()

    def _seed_complete_fixture(self) -> list[str]:
        bank = _bank()
        db_session.save_question_bank(bank)
        reached_ids = [
            "behavioral_01",
            "technical_01",
            "gap_probing_01",
            "situational_01",
            "closing_01",
        ]
        scores = [
            _score("behavioral_01", 9),
            _score("technical_01", 5),
            _score("gap_probing_01", 7),
            _score("situational_01", 6),
            _score("closing_01", 1, skipped=True),
        ]
        for score in scores:
            db_session.save_score("session-1", score.question_id, score)

        quotes = {
            "behavioral_01": [
                "I led the rollout and reduced support tickets by 30 percent.",
                "I coordinated with support and engineering every morning.",
            ],
            "technical_01": ["I used caching, but I did not measure the impact."],
            "gap_probing_01": ["I left that role because the project funding ended."],
            "situational_01": ["I would clarify the customer impact before changing scope."],
        }
        ts = 1.0
        for question_id, user_turns in quotes.items():
            db_session.save_transcript_entry("session-1", TranscriptEntry(
                speaker="agent",
                text=f"Question for {question_id}",
                question_id=question_id,
                ts=ts,
            ))
            ts += 1.0
            for turn in user_turns:
                db_session.save_transcript_entry("session-1", TranscriptEntry(
                    speaker="user",
                    text=turn,
                    question_id=question_id,
                    ts=ts,
                ))
                ts += 1.0
        db_session.save_transcript_entry("session-1", TranscriptEntry(
            speaker="agent",
            text="closing question",
            question_id="closing_01",
            ts=ts,
        ))
        return reached_ids

    def _narrative(self) -> str:
        return json.dumps({
            "top_moments": {
                "best_answer_question_id": "behavioral_01",
                "best_answer_quote": "I led the rollout and reduced support tickets by 30 percent.",
                "weakest_answer_question_id": "technical_01",
                "weakest_answer_quote": "I used caching, but I did not measure the impact.",
                "missed_opportunity_question_id": "technical_01",
                "missed_opportunity_summary": "The caching answer would improve with measured latency or cost impact.",
            },
            "per_question_feedback": [
                {
                    "question_id": "behavioral_01",
                    "category": "behavioral",
                    "question_text": "behavioral question 01?",
                    "answer_quote": "I led the rollout and reduced support tickets by 30 percent.",
                    "score": 9.0,
                    "strength": "Clear ownership and measurable outcome.",
                    "improvement_area": "Add one implementation detail.",
                    "suggested_rewrite": "I led the rollout, coordinated support and engineering, and reduced tickets by 30 percent.",
                    "skipped": False,
                },
                {
                    "question_id": "technical_01",
                    "category": "technical",
                    "question_text": "technical question 01?",
                    "answer_quote": "I used caching, but I did not measure the impact.",
                    "score": 5.0,
                    "strength": "Names the technical approach.",
                    "improvement_area": "Missing measured impact.",
                    "suggested_rewrite": "I used caching and would quantify latency before and after the change.",
                    "skipped": False,
                },
                {
                    "question_id": "gap_probing_01",
                    "category": "gap_probing",
                    "question_text": "gap_probing question 01?",
                    "answer_quote": "I left that role because the project funding ended.",
                    "score": 7.0,
                    "strength": "Gives a direct explanation.",
                    "improvement_area": "Could add what came next.",
                    "suggested_rewrite": "I left because funding ended, then I focused on roles where I could keep building.",
                    "skipped": False,
                },
                {
                    "question_id": "situational_01",
                    "category": "situational",
                    "question_text": "situational question 01?",
                    "answer_quote": "I would clarify the customer impact before changing scope.",
                    "score": 6.0,
                    "strength": "Shows customer-oriented judgment.",
                    "improvement_area": "Needs a more concrete sequence of actions.",
                    "suggested_rewrite": "I would clarify customer impact, list options, and align on scope with stakeholders.",
                    "skipped": False,
                },
                {
                    "question_id": "closing_01",
                    "category": "closing",
                    "question_text": "closing question 01?",
                    "answer_quote": None,
                    "score": None,
                    "strength": None,
                    "improvement_area": "Skipped answer.",
                    "suggested_rewrite": None,
                    "skipped": True,
                },
            ],
            "action_items": [
                {
                    "priority": 1,
                    "title": "Quantify technical impact",
                    "why_it_matters": "Your caching answer named an approach but not its outcome.",
                    "example_from_session": "I used caching, but I did not measure the impact.",
                    "practice_instruction": "Prepare before and after metrics for each technical example.",
                },
                {
                    "priority": 2,
                    "title": "Add implementation detail",
                    "why_it_matters": "Your strongest answer can become more memorable with how you did it.",
                    "example_from_session": "I led the rollout and reduced support tickets by 30 percent.",
                    "practice_instruction": "Add one sentence about the mechanism behind each result.",
                },
                {
                    "priority": 3,
                    "title": "Explain transitions crisply",
                    "why_it_matters": "Your role-exit explanation was direct and useful.",
                    "example_from_session": "I left that role because the project funding ended.",
                    "practice_instruction": "Pair each transition reason with what you intentionally pursued next.",
                },
                {
                    "priority": 4,
                    "title": "Sequence situational answers",
                    "why_it_matters": "Your judgment answer had the right instinct but needed steps.",
                    "example_from_session": "I would clarify the customer impact before changing scope.",
                    "practice_instruction": "Use a three-step structure: clarify, compare options, align.",
                },
                {
                    "priority": 5,
                    "title": "Show collaboration rhythm",
                    "why_it_matters": "Your follow-up added a useful operating detail.",
                    "example_from_session": "I coordinated with support and engineering every morning.",
                    "practice_instruction": "Mention who you worked with and how often when describing execution.",
                },
            ],
        })

    def test_synthesizes_report_with_deterministic_aggregates_and_order(self) -> None:
        reached_ids = self._seed_complete_fixture()

        with patch("backend.report.synthesizer._call_gemini", return_value=self._narrative()):
            report = synthesize_report("session-1")

        self.assertEqual(report.session_id, "session-1")
        self.assertEqual(report.overall_score, 6.8)
        self.assertEqual(report.dimension_breakdown.relevance, 6.8)
        self.assertEqual(
            [item.question_id for item in report.per_question_feedback],
            reached_ids,
        )
        closing = next(item for item in report.per_question_feedback if item.question_id == "closing_01")
        self.assertTrue(closing.skipped)
        self.assertIsNone(closing.score)

        categories = {item.category: item for item in report.category_breakdown}
        self.assertEqual(categories["closing"].answered_count, 0)
        self.assertEqual(categories["closing"].skipped_count, 1)
        self.assertEqual(categories["behavioral"].average_score, 9.0)

    def test_missing_score_for_reached_question_raises_before_gemini(self) -> None:
        bank = _bank()
        db_session.save_question_bank(bank)
        db_session.save_score("session-1", "behavioral_01", _score("behavioral_01", 8))
        db_session.save_transcript_entry("session-1", TranscriptEntry(
            speaker="user",
            text="I answered the first question.",
            question_id="behavioral_01",
            ts=1.0,
        ))
        db_session.save_transcript_entry("session-1", TranscriptEntry(
            speaker="user",
            text="This reached question has no score.",
            question_id="technical_01",
            ts=2.0,
        ))

        with patch("backend.report.synthesizer._call_gemini") as call:
            with self.assertRaises(ReportSynthesisError):
                synthesize_report("session-1")
        call.assert_not_called()

    def test_score_for_missing_question_raises_before_gemini(self) -> None:
        db_session.save_question_bank(_bank())
        db_session.save_score("session-1", "unknown_01", _score("unknown_01", 8))
        db_session.save_transcript_entry("session-1", TranscriptEntry(
            speaker="user",
            text="I answered something.",
            question_id="behavioral_01",
            ts=1.0,
        ))

        with patch("backend.report.synthesizer._call_gemini") as call:
            with self.assertRaises(ReportSynthesisError):
                synthesize_report("session-1")
        call.assert_not_called()

    def test_invented_quote_fails_validation(self) -> None:
        self._seed_complete_fixture()
        narrative = json.loads(self._narrative())
        narrative["top_moments"]["best_answer_quote"] = "I invented a metric that was never said."

        with patch("backend.report.synthesizer._call_gemini", return_value=json.dumps(narrative)):
            with self.assertRaises(ReportSynthesisError):
                synthesize_report("session-1")


if __name__ == "__main__":
    unittest.main()
