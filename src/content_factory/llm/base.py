"""Base LLM provider interface with structured-output helper."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences wrapping JSON."""
    m = _FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    return text.strip()


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def generate_text(self, system: str, user: str) -> str:
        """Send system + user messages and return the assistant response text."""
        ...

    def generate_pydantic(
        self,
        system: str,
        user: str,
        schema: Type[T],
        retries: int = 2,
    ) -> T:
        """Generate text, parse it as JSON, and validate against a Pydantic model.

        Retries with a nudge if parsing fails.
        """
        last_error: Exception | None = None
        for attempt in range(1, retries + 2):
            nudge = ""
            if attempt > 1:
                nudge = (
                    "\n\nIMPORTANT: Return ONLY valid JSON matching the schema. "
                    "No markdown, no code fences, no commentary."
                )
            raw = self.generate_text(system + nudge, user)
            cleaned = _strip_code_fences(raw)
            try:
                data = json.loads(cleaned)
                return schema.model_validate(data)
            except (json.JSONDecodeError, Exception) as exc:
                last_error = exc
                continue
        raise ValueError(
            f"Failed to parse LLM output as {schema.__name__} after {retries + 1} attempts. "
            f"Last error: {last_error}"
        )
