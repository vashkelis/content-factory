"""Minimal LangGraph pipeline for content-factory.

Currently implements a single-node graph for ContentCore synthesis.
Designed to be extended with blog/linkedin/x rendering nodes later.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from content_factory.llm.base import LLMProvider
from content_factory.models import Brief, ContentCore
from content_factory.resources import read_text, read_yaml


# ── Graph state ──────────────────────────────────────────────────────────────

class PipelineState(BaseModel):
    """State that flows through the content pipeline graph."""

    brief: Dict[str, Any]
    style_profile: Dict[str, Any] = Field(default_factory=dict)
    core: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# ── Node implementations ─────────────────────────────────────────────────────

def _make_core_synth_node(provider: LLMProvider):
    """Return a node function that synthesizes a ContentCore from the brief."""

    def core_synth(state: PipelineState) -> dict:
        brief = Brief.model_validate(state.brief)
        style = state.style_profile

        # Load prompt template
        prompt_template = read_text("prompts/core_synth.txt")

        # Build the forbidden-phrases block
        forbidden: list[str] = []
        ai_smell = style.get("forbidden_ai_smell", {})
        if isinstance(ai_smell, dict):
            forbidden = ai_smell.get("avoid_phrases", [])
        forbidden_block = "\n".join(f"  - {p}" for p in forbidden) if forbidden else "(none)"

        system_prompt = prompt_template.format(
            forbidden_phrases=forbidden_block,
        )

        user_prompt = (
            f"Topic: {brief.topic}\n"
            f"Goal: {brief.goal}\n"
            f"Audience: {brief.audience}\n"
            f"Language: {brief.language}\n"
            f"Platforms: {', '.join(brief.platform_targets)}\n"
        )
        if brief.context_notes:
            user_prompt += f"Context / sources: {brief.context_notes}\n"
        else:
            user_prompt += "Context / sources: NONE PROVIDED. Do NOT invent specific facts or statistics.\n"
        if brief.constraints:
            user_prompt += "Constraints:\n"
            for k, v in brief.constraints.items():
                user_prompt += f"  {k}: {v}\n"

        try:
            core = provider.generate_pydantic(
                system=system_prompt,
                user=user_prompt,
                schema=ContentCore,
                retries=2,
            )
            return {"core": core.model_dump()}
        except Exception as exc:
            return {"error": str(exc)}

    return core_synth


# ── Graph builder ────────────────────────────────────────────────────────────

def build_core_graph(provider: LLMProvider) -> StateGraph:
    """Build and compile a LangGraph graph for ContentCore synthesis."""
    graph = StateGraph(PipelineState)
    graph.add_node("core_synth", _make_core_synth_node(provider))
    graph.set_entry_point("core_synth")
    graph.add_edge("core_synth", END)
    return graph.compile()


def run_core_pipeline(
    brief: Brief,
    provider: LLMProvider,
    style_profile: dict | None = None,
) -> tuple[ContentCore | None, str | None]:
    """Run the core-synthesis pipeline and return (core, error).

    Returns (ContentCore, None) on success, (None, error_message) on failure.
    """
    if style_profile is None:
        style_profile = read_yaml("profiles/style_profile.yaml")

    compiled = build_core_graph(provider)
    initial_state = PipelineState(
        brief=brief.model_dump(),
        style_profile=style_profile,
    )
    result = compiled.invoke(initial_state)

    # LangGraph returns a dict (or AddableValuesDict)
    if isinstance(result, dict):
        error = result.get("error")
        core_data = result.get("core")
    else:
        error = getattr(result, "error", None)
        core_data = getattr(result, "core", None)

    if error:
        return None, error
    if core_data:
        return ContentCore.model_validate(core_data), None
    return None, "Pipeline produced no output."
