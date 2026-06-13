import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
import sqlite3
import gc

from pydantic import ValidationError

from backend.db import session as db_session
from backend.schemas.scoring import ScoreResult


class ScoreResultTests(unittest.TestCase):
    def test_computes_overall_from_dimensions(self) -> None:
        score = ScoreResult.model_validate({
            "question_id": "q1",
            "skipped": False,
            "relevance": 8,
            "specificity": 7,
            "structure": 9,
            "communication": 6,
            "overall": 1.0,
            "strongest_moment": "I reduced latency by 20 percent.",
            "weakest_moment": "I helped with the project.",
            "suggested_rewrite": "I owned the API changes and measured a 20 percent latency drop.",
        })

        self.assertEqual(score.overall, 7.5)

    def test_coerces_float_scores_to_ints(self) -> None:
        score = ScoreResult.model_validate({
            "question_id": "q1",
            "skipped": False,
            "relevance": 8.0,
            "specificity": 7.0,
            "structure": 9.0,
            "communication": 6.0,
            "strongest_moment": "I reduced latency by 20 percent.",
            "weakest_moment": "I helped with the project.",
            "suggested_rewrite": "I owned the API changes and measured a 20 percent latency drop.",
        })

        self.assertEqual(score.relevance, 8)
        self.assertEqual(score.overall, 7.5)

    def test_skipped_requires_all_analysis_fields_null(self) -> None:
        with self.assertRaises(ValidationError):
            ScoreResult.model_validate({
                "question_id": "q1",
                "skipped": True,
                "relevance": None,
                "specificity": None,
                "structure": None,
                "communication": None,
                "overall": 1.0,
                "strongest_moment": None,
                "weakest_moment": None,
                "suggested_rewrite": None,
            })

    def test_non_skipped_requires_all_score_dimensions(self) -> None:
        with self.assertRaises(ValidationError):
            ScoreResult.model_validate({
                "question_id": "q1",
                "skipped": False,
                "relevance": 8,
                "specificity": None,
                "structure": 9,
                "communication": 6,
                "strongest_moment": "I reduced latency by 20 percent.",
                "weakest_moment": "I helped with the project.",
                "suggested_rewrite": "I owned the API changes and measured a 20 percent latency drop.",
            })


class ScoreStorageTests(unittest.TestCase):
    def test_save_score_rejects_duplicates_and_get_scores_preserves_order(self) -> None:
        original_db_path = db_session._DB_PATH
        try:
            with TemporaryDirectory() as tmpdir:
                db_session._DB_PATH = Path(tmpdir) / "scores.db"
                first = ScoreResult.model_validate({
                    "question_id": "q1",
                    "skipped": False,
                    "relevance": 8,
                    "specificity": 7,
                    "structure": 9,
                    "communication": 6,
                    "strongest_moment": "I reduced latency by 20 percent.",
                    "weakest_moment": "I helped with the project.",
                    "suggested_rewrite": "I owned the API changes and measured a 20 percent latency drop.",
                })
                second = ScoreResult.model_validate({
                    "question_id": "q2",
                    "skipped": True,
                    "relevance": None,
                    "specificity": None,
                    "structure": None,
                    "communication": None,
                    "strongest_moment": None,
                    "weakest_moment": None,
                    "suggested_rewrite": None,
                })

                db_session.save_score("session-1", "q1", first)
                db_session.save_score("session-1", "q2", second)

                with self.assertRaises(sqlite3.IntegrityError):
                    db_session.save_score("session-1", "q1", first)

                scores = db_session.get_scores("session-1")
                self.assertEqual([score.question_id for score in scores], ["q1", "q2"])
                self.assertEqual(scores[0].overall, 7.5)
                self.assertTrue(scores[1].skipped)
                del scores
                gc.collect()
        finally:
            db_session._DB_PATH = original_db_path


if __name__ == "__main__":
    unittest.main()
