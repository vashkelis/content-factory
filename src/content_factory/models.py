"""Pydantic v2 data models for content-factory."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

Platform = Literal["blog", "linkedin", "x"]
Lang = Literal["ru", "en"]
ARTIFACT_NAMES = ("meta", "brief", "core", "blog", "linkedin", "x")


# ── Brief ────────────────────────────────────────────────────────────────────

class Brief(BaseModel):
    topic: str
    goal: str = "inform"
    audience: str = "builders, founders, product people"
    platform_targets: List[Platform] = Field(default_factory=lambda: ["blog", "linkedin", "x"])
    language: Lang = "ru"
    context_notes: Optional[str] = None
    constraints: Dict[str, str] = Field(default_factory=dict)


# ── Content Core ─────────────────────────────────────────────────────────────

class CorePoint(BaseModel):
    claim: str
    support: List[str]
    example: Optional[str] = None


class ContentCore(BaseModel):
    thesis: str
    angle: str
    points: List[CorePoint]
    optional_counterpoint: Optional[str] = None
    product_update: bool = False
    do_not_say: List[str] = Field(default_factory=list)
    source_notes: Optional[str] = None


# ── Run Metadata ─────────────────────────────────────────────────────────────

class RunMeta(BaseModel):
    run_id: str
    topic: str
    language: Lang
    status: str = "initialized"
    model: Optional[str] = None
    error_message: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ── Placeholders for future nodes ────────────────────────────────────────────

class QAReport(BaseModel):
    """Placeholder for quality-assurance report."""
    issues: List[str] = Field(default_factory=list)
    passed: bool = True


class DraftPack(BaseModel):
    """Placeholder for rendered drafts across platforms."""
    blog: Optional[str] = None
    linkedin: Optional[str] = None
    x: Optional[str] = None
