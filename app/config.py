import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.z.ai/api/paas/v4").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "glm-4.5-flash")
LLM_PRICE_INPUT_PER_M = float(os.getenv("LLM_PRICE_INPUT_PER_M", "0"))
LLM_PRICE_OUTPUT_PER_M = float(os.getenv("LLM_PRICE_OUTPUT_PER_M", "0"))

# Extra JSON merged into the chat payload, for provider-specific knobs
# (e.g. z.ai: {"thinking": {"type": "disabled"}} to skip reasoning tokens).
try:
    LLM_EXTRA_BODY: dict = json.loads(os.getenv("LLM_EXTRA_BODY", "{}") or "{}")
except json.JSONDecodeError:
    LLM_EXTRA_BODY = {}

ROUTE_THRESHOLD = float(os.getenv("ROUTE_THRESHOLD", "0.80"))

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
PAGE_DIR = DATA_DIR / "pages"
DB_PATH = DATA_DIR / "paperflow.db"

TESSERACT_CMD = os.getenv("TESSERACT_CMD", "")


def ensure_dirs() -> None:
    for d in (DATA_DIR, UPLOAD_DIR, PAGE_DIR):
        d.mkdir(parents=True, exist_ok=True)
