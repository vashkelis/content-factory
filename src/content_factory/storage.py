"""Filesystem storage helpers for content-factory runs."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional


def slugify(topic: str, max_len: int = 60) -> str:
    """Create a filesystem-safe slug from a unicode topic string.

    - Lowercases
    - Keeps alphanumeric and unicode letters
    - Replaces whitespace / separators with '-'
    - Collapses consecutive dashes
    - Trims to *max_len* characters
    """
    text = topic.lower()
    # Replace any whitespace / common separators with a single dash
    text = re.sub(r"[\s_/\\:;.,!?]+", "-", text)
    # Keep only word-characters (unicode-aware) and dashes
    text = re.sub(r"[^\w-]", "", text, flags=re.UNICODE)
    # Collapse multiple dashes
    text = re.sub(r"-{2,}", "-", text)
    text = text.strip("-")
    return text[:max_len]


@dataclass
class RunPaths:
    """Convenience container for the paths inside a run directory."""

    run_dir: Path
    brief_json: Path
    meta_json: Path
    core_json: Path
    blog_md: Path
    linkedin_md: Path
    x_md: Path

    @property
    def run_id(self) -> str:
        return self.run_dir.name


def create_run_dir(base_dir: str | Path, topic: str) -> RunPaths:
    """Create a timestamped run folder and return paths to its artifacts."""
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    slug = slugify(topic)
    run_name = f"{ts}_{slug}" if slug else ts
    run_dir = base / run_name
    run_dir.mkdir(parents=True, exist_ok=False)

    paths = RunPaths(
        run_dir=run_dir,
        brief_json=run_dir / "brief.json",
        meta_json=run_dir / "meta.json",
        core_json=run_dir / "core.json",
        blog_md=run_dir / "blog.md",
        linkedin_md=run_dir / "linkedin.md",
        x_md=run_dir / "x.md",
    )
    return paths


def write_json(path: Path, data: Any) -> None:
    """Write *data* as pretty-printed JSON."""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    """Read and parse a JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, content: str) -> None:
    """Write text content to a file, creating parent dirs if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def list_runs(base_dir: str | Path, limit: int = 20) -> List[str]:
    """Return run directory names sorted newest-first."""
    base = Path(base_dir)
    if not base.is_dir():
        return []
    dirs = sorted(
        [d.name for d in base.iterdir() if d.is_dir()],
        reverse=True,
    )
    return dirs[:limit]


def find_run_dir(base_dir: str | Path, run_id: str) -> Optional[Path]:
    """Find a run directory by exact name or prefix match."""
    base = Path(base_dir)
    exact = base / run_id
    if exact.is_dir():
        return exact
    # Try prefix match
    for d in sorted(base.iterdir(), reverse=True):
        if d.is_dir() and d.name.startswith(run_id):
            return d
    return None


def artifact_path(run_dir: str | Path, name: str) -> Path:
    """Return path for an artifact by short name (meta, brief, core, blog, linkedin, x)."""
    run = Path(run_dir)
    mapping = {
        "meta": run / "meta.json",
        "brief": run / "brief.json",
        "core": run / "core.json",
        "blog": run / "blog.md",
        "linkedin": run / "linkedin.md",
        "x": run / "x.md",
    }
    if name not in mapping:
        raise ValueError(f"Unknown artifact '{name}'. Choose from: {', '.join(mapping)}")
    return mapping[name]


# ── Versioning helpers ───────────────────────────────────────────────────────

def version_artifact(run_dir: Path, platform: str) -> int:
    """Back up the current platform draft to a versioned copy.

    E.g. linkedin.md -> linkedin_v1.md.  Returns the version number assigned.
    """
    current = artifact_path(run_dir, platform)
    if not current.exists():
        return 0

    # Find next version number by scanning existing versioned files
    version = 1
    while (run_dir / f"{platform}_v{version}.md").exists():
        version += 1

    dest = run_dir / f"{platform}_v{version}.md"
    dest.write_text(current.read_text(encoding="utf-8"), encoding="utf-8")
    return version


# ── Prompts subdir (stores prompts used in a run for auditability) ───────────

def save_run_prompt(run_dir: Path, name: str, content: str) -> Path:
    """Save a prompt that was used during a run for reproducibility.

    Written to runs/<run_id>/prompts/<name>.  Returns the path.
    """
    prompts_dir = run_dir / "prompts"
    prompts_dir.mkdir(exist_ok=True)
    path = prompts_dir / name
    path.write_text(content, encoding="utf-8")
    return path


# ── Patch storage ────────────────────────────────────────────────────────────

def next_patch_number(run_dir: Path, platform: str) -> int:
    """Return the next patch sequence number for a given platform."""
    patches_dir = run_dir / "patches"
    if not patches_dir.is_dir():
        return 1
    existing = sorted(patches_dir.glob(f"*_{platform}.json"))
    return len(existing) + 1


def save_patch_record(run_dir: Path, record_data: dict, platform: str, number: int) -> Path:
    """Write a patch record JSON file.  Returns the path."""
    patches_dir = run_dir / "patches"
    patches_dir.mkdir(exist_ok=True)
    filename = f"{number:03d}_{platform}.json"
    path = patches_dir / filename
    write_json(path, record_data)
    return path
