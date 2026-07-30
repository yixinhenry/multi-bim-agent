from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv() -> bool:
        return False


load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("BIM_MULTI_DATA_DIR", ROOT / "data")).resolve()
PROJECTS_DIR = DATA_DIR / "projects"
DB_PATH = DATA_DIR / "platform.db"
MODEL_NAME = os.getenv("BIM_MULTI_MODEL", "deepseek-chat")
BASE_URL = os.getenv("BIM_MULTI_BASE_URL", "https://api.deepseek.com")
API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
TEMPERATURE = float(os.getenv("BIM_MULTI_TEMPERATURE", "0"))
