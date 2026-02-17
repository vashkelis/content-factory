"""Resource loading helpers: prompts, profiles, specs.

Supports a split between public and private resources:
- Public resources are bundled with the package (prompts/, profiles/, examples/)
- Private resources are stored separately (set CONTENT_FACTORY_PRIVATE_DIR env var)

The private directory takes precedence if set and file exists there.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

# The repo root is three levels up from this file:
#   src/content_factory/resources.py -> ../../..
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def get_private_dir() -> Path | None:
    """Return the private resources directory if configured and exists."""
    private_dir = os.environ.get("CONTENT_FACTORY_PRIVATE_DIR")
    if private_dir:
        p = Path(private_dir).expanduser().resolve()
        if p.is_dir():
            return p
    return None


def _resolve(rel_path: str) -> Path:
    """Resolve a path, checking private directory first.

    Resolution order:
    1. CONTENT_FACTORY_PRIVATE_DIR/<rel_path> if env var is set
    2. _REPO_ROOT/<rel_path> as fallback
    """
    # Check private directory first
    private_dir = get_private_dir()
    if private_dir:
        private_path = private_dir / rel_path
        if private_path.exists():
            return private_path

    # Fall back to repo root
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
