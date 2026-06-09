"""CLI entry point: generate a question bank from a stored resume.

Usage:
    python -m backend.generate_questions <resume_id>
"""

import sys
import time
from collections import Counter

from backend.db.session import get_resume, save_question_bank
from backend.question_gen.generator import generate_question_bank
from backend.schemas.resume import ResumeData


def main(resume_id: str) -> None:
    row = get_resume(resume_id)
    if row is None:
        print(f"ERROR: No resume found for id '{resume_id}'")
        sys.exit(1)

    resume = ResumeData.model_validate(row["structured_json"])
    session_id = f"{resume_id}_{int(time.time())}"

    print(f"Generating question bank for: {resume.name}")
    print(f"Session ID: {session_id}")
    print(f"Gap analysis items: {len(resume.gap_analysis)}\n")

    bank = generate_question_bank(resume, session_id)
    save_question_bank(bank)

    counts = Counter(q.category for q in bank.questions)
    print("── Category counts ─────────────────────────")
    for category, count in sorted(counts.items()):
        print(f"  {category:<15} {count}")
    print(f"  {'TOTAL':<15} {sum(counts.values())}")
    print()

    print("── All 28 questions ────────────────────────")
    for q in bank.questions:
        print(f"\n[{q.id}] ({q.category})")
        print(f"  Q:            {q.text}")
        if q.source_ref:
            print(f"  source_ref:   {q.source_ref}")
        print(f"  vague f/u:    {q.follow_up_vague}")
        print(f"  strong f/u:   {q.follow_up_strong}")

    print(f"\nStored in SQLite — session_id: {session_id}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m backend.generate_questions <resume_id>")
        sys.exit(1)
    main(sys.argv[1])
