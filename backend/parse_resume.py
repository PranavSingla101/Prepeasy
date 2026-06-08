"""CLI entry-point: python -m backend.parse_resume <path/to/resume.pdf>"""
import json
import sys
import time
from pathlib import Path

from backend.parser.extractor import extract_text
from backend.parser.structured import extract_structured
from backend.schemas.resume import ResumeData
from backend.db.session import save_resume


def parse(pdf_path: str) -> dict:
    t0 = time.time()
    path = Path(pdf_path)

    raw_text = extract_text(str(path))
    if len(raw_text.strip()) < 200:
        raise ValueError(f"Extracted text too short ({len(raw_text.strip())} chars) — check the PDF")

    resume_data: ResumeData = extract_structured(raw_text)
    resume_id = save_resume(path.name, raw_text, resume_data.model_dump())

    elapsed = time.time() - t0
    return {
        "resume_id": resume_id,
        "elapsed_seconds": round(elapsed, 2),
        "structured": resume_data.model_dump(),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m backend.parse_resume <path/to/resume.pdf>")
        sys.exit(1)

    result = parse(sys.argv[1])
    print(f"\nresume_id : {result['resume_id']}")
    print(f"elapsed   : {result['elapsed_seconds']}s")
    print("\ngap_analysis:")
    for item in result["structured"]["gap_analysis"]:
        print(f"  - {item}")
    print("\n--- full structured output ---")
    print(json.dumps(result["structured"], indent=2))
