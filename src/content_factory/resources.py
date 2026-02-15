"""Resource loading helpers: prompts, profiles, specs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# The repo root is three levels up from this file:
#   src/content_factory/resources.py -> ../../..
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve(rel_path: str) -> Path:
    """Resolve a path relative to the repository root."""
    p = _REPO_ROOT / rel_path
    if not p.exists():
        raise FileNotFoundError(f"Resource not found: {p}")
    return p


def read_text(rel_path: str) -> str:
    """Read a text file relative to the repo root."""
    return _resolve(rel_path).read_text(encoding="utf-8")


def read_yaml(rel_path: str) -> Any:
    """Read and parse a YAML file relative to the repo root."""
    text = read_text(rel_path)
    return yaml.safe_load(text)
