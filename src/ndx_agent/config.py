"""Environment-driven configuration."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

CACHE_DIR = ROOT / ".cache"


def get(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    return value or default


ANTHROPIC_MODEL = get("ANTHROPIC_MODEL", "claude-sonnet-4-5")
SEC_USER_AGENT = get("SEC_USER_AGENT", "ndx-agent contact@example.com")
