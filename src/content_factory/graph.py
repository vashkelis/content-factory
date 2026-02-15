"""LangGraph pipelines for content-factory.

Pipelines:
  - clarify:  Evaluate whether a brief needs clarification before core generation.
  - core:     Synthesize a ContentCore JSON from a brief.
  - render:   Render a platform-specific draft from ContentCore (linkedin first).
  - patch:    Apply a minimal directive-based rewrite to an existing draft.
"""

from __future__ import annotations

import json
import string
from typing import Any, Dict, List, Optional

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from content_factory.llm.base import LLMProvider
from content_factory.models import Brief, ClarificationResult, ContentCore
from content_factory.resources import read_text, read_yaml


# ── Shared helpers ───────────────────────────────────────────────────────────

def _get_forbidden_phrases(style: dict) -> list[str]:
    """Extract forbidden AI-smell phrases from a style profile dict."""
    ai_smell = style.get("forbidden_ai_smell", {})
    if isinstance(ai_smell, dict):
        return ai_smell.get("avoid_phrases", [])
    return []


def _format_forbidden_block(phrases: list[str]) -> str:
    return "\n".join(f"  - {p}" for p in phrases) if phrases else "(none)"


def _build_brief_summary(brief: Brief) -> str:
    """Build a human-readable brief summary for prompts."""
    lines = [
        f"Topic: {brief.topic}",
        f"Goal: {brief.goal}",
        f"Audience: {brief.audience}",
        f"Language: {brief.language}",
        f"Platforms: {', '.join(brief.platform_targets)}",
    ]
    if brief.context_notes:
        lines.append(f"Context / sources: {brief.context_notes}")
    else:
        lines.append("Context / sources: NONE PROVIDED. Do NOT invent specific facts or statistics.")
    if brief.constraints:
        lines.append("Constraints:")
        for k, v in brief.constraints.items():
            lines.append(f"  {k}: {v}")
    return "\n".join(lines)


def _check_forbidden_in_text(text: str, phrases: list[str]) -> list[str]:
    """Return any forbidden phrases found in the text (case-insensitive)."""
    lower = text.lower()
    return [p for p in phrases if p.lower() in lower]


def _safe_format(template: str, **kwargs: str) -> str:
    """Substitute {key} placeholders without raising on unrecognised braces.

    Python's str.format() fails when the template contains literal JSON braces.
    This helper only replaces explicitly provided keys and leaves everything
    else untouched.
    """
    for key, value in kwargs.items():
        template = template.replace("{" + key + "}", value)
    return template


# ══════════════════════════════════════════════════════════════════════════════
# PIPELINE 1: Clarification
# ══════════════════════════════════════════════════════════════════════════════

class ClarifyState(BaseModel):
    brief: Dict[str, Any]
    style_profile: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


def _make_clarify_node(provider: LLMProvider):
    def clarify(state: ClarifyState) -> dict:
        brief = Brief.model_validate(state.brief)
        prompt_template = read_text("prompts/clarify.txt")
        system_prompt = prompt_template
        user_prompt = _build_brief_summary(brief)
        try:
            result = provider.generate_pydantic(
                system=system_prompt,
                user=user_prompt,
                schema=ClarificationResult,
                retries=2,
            )
            return {"result": result.model_dump()}
        except Exception as exc:
            return {"error": str(exc)}
    return clarify


def run_clarify_pipeline(
    brief: Brief,
    provider: LLMProvider,
) -> tuple[ClarificationResult | None, str | None]:
    """Evaluate whether the brief needs clarification.

    Returns (ClarificationResult, None) on success, (None, error) on failure.
    """
    graph = StateGraph(ClarifyState)
    graph.add_node("clarify", _make_clarify_node(provider))
    graph.set_entry_point("clarify")
    graph.add_edge("clarify", END)
    compiled = graph.compile()

    result = compiled.invoke(ClarifyState(brief=brief.model_dump()))
    if isinstance(result, dict):
        error = result.get("error")
        data = result.get("result")
    else:
        error = getattr(result, "error", None)
        data = getattr(result, "result", None)

    if error:
        return None, error
    if data:
        return ClarificationResult.model_validate(data), None
    return None, "Clarify pipeline produced no output."


# ══════════════════════════════════════════════════════════════════════════════
# PIPELINE 2: Core synthesis
# ══════════════════════════════════════════════════════════════════════════════

class CoreState(BaseModel):
    brief: Dict[str, Any]
    style_profile: Dict[str, Any] = Field(default_factory=dict)
    core: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


def _make_core_synth_node(provider: LLMProvider):
    """Return a node function that synthesizes a ContentCore from the brief."""

    def core_synth(state: CoreState) -> dict:
        brief = Brief.model_validate(state.brief)
        style = state.style_profile

        prompt_template = read_text("prompts/core_synth.txt")
        forbidden_block = _format_forbidden_block(_get_forbidden_phrases(style))

        system_prompt = _safe_format(prompt_template, forbidden_phrases=forbidden_block)
        user_prompt = _build_brief_summary(brief)

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


def build_core_graph(provider: LLMProvider):
    """Build and compile a LangGraph graph for ContentCore synthesis."""
    graph = StateGraph(CoreState)
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
    initial_state = CoreState(
        brief=brief.model_dump(),
        style_profile=style_profile,
    )
    result = compiled.invoke(initial_state)

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


# ══════════════════════════════════════════════════════════════════════════════
# PIPELINE 3: Render (LinkedIn first, extensible to blog/x)
# ══════════════════════════════════════════════════════════════════════════════

class RenderState(BaseModel):
    brief: Dict[str, Any]
    core: Dict[str, Any]
    style_profile: Dict[str, Any] = Field(default_factory=dict)
    platform_spec: Dict[str, Any] = Field(default_factory=dict)
    platform: str = "linkedin"
    rendered_text: Optional[str] = None
    system_prompt_used: Optional[str] = None
    error: Optional[str] = None


def _make_render_node(provider: LLMProvider):
    """Render node: generates platform-specific text from ContentCore.

    Post-generation validation:
      - Length bounds check (retry once with shorten instruction)
      - Forbidden phrase check (retry once with correction instruction)
    """

    def render(state: RenderState) -> dict:
        brief = Brief.model_validate(state.brief)
        core = ContentCore.model_validate(state.core)
        style = state.style_profile
        spec = state.platform_spec
        platform = state.platform

        prompt_template = read_text(f"prompts/render_{platform}.txt")
        forbidden = _get_forbidden_phrases(style)
        forbidden_block = _format_forbidden_block(forbidden)

        # Build voice rules summary
        voice = style.get("voice", {})
        voice_rules = (
            f"Tone: {voice.get('tone', 'direct')}\n"
            f"Perspective: {voice.get('perspective', 'practitioner')}\n"
            f"Avoid: {', '.join(voice.get('avoid', []))}"
        )

        # Emoji policy from spec
        formatting = spec.get("formatting", {})
        emoji_policy = formatting.get("emojis", "sparingly, max 2-3")

        min_chars = spec.get("min_length_chars", 500)
        max_chars = spec.get("max_length_chars", 3000)

        system_prompt = _safe_format(
            prompt_template,
            language=brief.language,
            min_chars=str(min_chars),
            max_chars=str(max_chars),
            forbidden_phrases=forbidden_block,
            core_json=json.dumps(core.model_dump(), ensure_ascii=False, indent=2),
            platform_spec=json.dumps(spec, ensure_ascii=False, indent=2),
            voice_rules=voice_rules,
            emoji_policy=emoji_policy,
        )
        user_prompt = f"Write the {platform} post now."

        try:
            text = provider.generate_text(system_prompt, user_prompt)
        except Exception as exc:
            return {"error": str(exc), "system_prompt_used": system_prompt}

        # ── Validation pass 1: length bounds ─────────────────────────────
        # Use reasonable validation bounds (slightly wider than prompt asks)
        validation_min = 300
        validation_max = 3200
        if len(text) > validation_max:
            try:
                text = provider.generate_text(
                    system_prompt + "\n\nThe previous output was too long. Shorten it by 15%. "
                    f"Stay under {max_chars} characters.",
                    user_prompt,
                )
            except Exception as exc:
                return {"error": f"Length retry failed: {exc}", "system_prompt_used": system_prompt}

        # ── Validation pass 2: forbidden phrases ─────────────────────────
        found = _check_forbidden_in_text(text, forbidden)
        if found:
            correction = (
                "\n\nCRITICAL: The previous output contained forbidden phrases: "
                + ", ".join(f'"{p}"' for p in found)
                + ". Rewrite without them. Return ONLY the post text."
            )
            try:
                text = provider.generate_text(system_prompt + correction, user_prompt)
            except Exception as exc:
                return {
                    "error": f"Forbidden phrase retry failed: {exc}",
                    "system_prompt_used": system_prompt,
                }

        return {
            "rendered_text": text.strip(),
            "system_prompt_used": system_prompt,
        }

    return render


def run_render_pipeline(
    brief: Brief,
    core: ContentCore,
    provider: LLMProvider,
    platform: str = "linkedin",
    style_profile: dict | None = None,
    platform_spec: dict | None = None,
) -> tuple[str | None, str | None, str | None]:
    """Run the render pipeline.

    Returns (rendered_text, system_prompt_used, error).
    """
    if style_profile is None:
        style_profile = read_yaml("profiles/style_profile.yaml")
    if platform_spec is None:
        platform_spec = read_yaml(f"specs/platform_{platform}.yaml")

    graph = StateGraph(RenderState)
    graph.add_node("render", _make_render_node(provider))
    graph.set_entry_point("render")
    graph.add_edge("render", END)
    compiled = graph.compile()

    initial = RenderState(
        brief=brief.model_dump(),
        core=core.model_dump(),
        style_profile=style_profile,
        platform_spec=platform_spec,
        platform=platform,
    )
    result = compiled.invoke(initial)

    if isinstance(result, dict):
        error = result.get("error")
        text = result.get("rendered_text")
        prompt_used = result.get("system_prompt_used")
    else:
        error = getattr(result, "error", None)
        text = getattr(result, "rendered_text", None)
        prompt_used = getattr(result, "system_prompt_used", None)

    if error:
        return None, prompt_used, error
    return text, prompt_used, None


# ══════════════════════════════════════════════════════════════════════════════
# PIPELINE 4: Patch
# ══════════════════════════════════════════════════════════════════════════════

CHANGELOG_SEPARATOR = "---CHANGELOG---"


class PatchState(BaseModel):
    draft: str
    directive: str
    style_profile: Dict[str, Any] = Field(default_factory=dict)
    patched_text: Optional[str] = None
    changelog: Optional[str] = None
    system_prompt_used: Optional[str] = None
    error: Optional[str] = None


def _make_patch_node(provider: LLMProvider):
    def patch_apply(state: PatchState) -> dict:
        style = state.style_profile
        forbidden = _get_forbidden_phrases(style)
        forbidden_block = _format_forbidden_block(forbidden)

        voice = style.get("voice", {})
        voice_rules = (
            f"Tone: {voice.get('tone', 'direct')}\n"
            f"Perspective: {voice.get('perspective', 'practitioner')}\n"
            f"Avoid: {', '.join(voice.get('avoid', []))}"
        )

        prompt_template = read_text("prompts/patch.txt")
        system_prompt = _safe_format(
            prompt_template,
            forbidden_phrases=forbidden_block,
            draft=state.draft,
            directive=state.directive,
            voice_rules=voice_rules,
        )
        user_prompt = "Apply the patch now."

        try:
            raw = provider.generate_text(system_prompt, user_prompt)
        except Exception as exc:
            return {"error": str(exc), "system_prompt_used": system_prompt}

        # Split output at CHANGELOG separator
        changelog = ""
        patched = raw.strip()
        if CHANGELOG_SEPARATOR in raw:
            parts = raw.split(CHANGELOG_SEPARATOR, 1)
            patched = parts[0].strip()
            changelog = parts[1].strip()

        # Validate no forbidden phrases in output
        found = _check_forbidden_in_text(patched, forbidden)
        if found:
            correction = (
                "\n\nCRITICAL: The output contained forbidden phrases: "
                + ", ".join(f'"{p}"' for p in found)
                + ". Rewrite without them. Keep the ---CHANGELOG--- section."
            )
            try:
                raw2 = provider.generate_text(system_prompt + correction, user_prompt)
                if CHANGELOG_SEPARATOR in raw2:
                    parts2 = raw2.split(CHANGELOG_SEPARATOR, 1)
                    patched = parts2[0].strip()
                    changelog = parts2[1].strip()
                else:
                    patched = raw2.strip()
            except Exception as exc:
                return {"error": f"Forbidden phrase retry failed: {exc}", "system_prompt_used": system_prompt}

        return {
            "patched_text": patched,
            "changelog": changelog,
            "system_prompt_used": system_prompt,
        }

    return patch_apply


def run_patch_pipeline(
    draft: str,
    directive: str,
    provider: LLMProvider,
    style_profile: dict | None = None,
) -> tuple[str | None, str | None, str | None, str | None]:
    """Run the patch pipeline.

    Returns (patched_text, changelog, system_prompt_used, error).
    """
    if style_profile is None:
        style_profile = read_yaml("profiles/style_profile.yaml")

    graph = StateGraph(PatchState)
    graph.add_node("patch_apply", _make_patch_node(provider))
    graph.set_entry_point("patch_apply")
    graph.add_edge("patch_apply", END)
    compiled = graph.compile()

    initial = PatchState(
        draft=draft,
        directive=directive,
        style_profile=style_profile,
    )
    result = compiled.invoke(initial)

    if isinstance(result, dict):
        error = result.get("error")
        text = result.get("patched_text")
        changelog = result.get("changelog")
        prompt_used = result.get("system_prompt_used")
    else:
        error = getattr(result, "error", None)
        text = getattr(result, "patched_text", None)
        changelog = getattr(result, "changelog", None)
        prompt_used = getattr(result, "system_prompt_used", None)

    if error:
        return None, None, prompt_used, error
    return text, changelog, prompt_used, None
