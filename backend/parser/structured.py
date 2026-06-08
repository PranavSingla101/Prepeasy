import json
import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

from backend.schemas.resume import ResumeData

load_dotenv()

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "extraction_v1.txt"
_PROMPT_TEMPLATE = _PROMPT_PATH.read_text(encoding="utf-8")

_MODEL = "gemini-2.5-flash"


def extract_structured(raw_text: str) -> ResumeData:
    """Send raw resume text to Gemini and return a validated ResumeData object."""
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    prompt = _PROMPT_TEMPLATE.replace("{resume_text}", raw_text)

    response = client.models.generate_content(
        model=_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.0,
        ),
    )

    text = response.text.strip()
    # Strip markdown fences if the model wraps anyway
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    data = json.loads(text)
    return ResumeData.model_validate(data)
