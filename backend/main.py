"""FastAPI application entry point.

Run with:
    Interv\\Scripts\\uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
"""
import logging

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(title="Interview Agent")

from backend.api.interview import router as interview_router  # noqa: E402
from backend.api.report import router as report_router  # noqa: E402

app.include_router(interview_router)
app.include_router(report_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
