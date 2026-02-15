"""OpenAI-based LLM provider."""

from __future__ import annotations

import os

from openai import OpenAI

from content_factory.llm.base import LLMProvider


class OpenAIProvider(LLMProvider):
    """LLM provider backed by the OpenAI chat completions API."""

    def __init__(self, model: str = "gpt-4o-mini", temperature: float = 0.4) -> None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "OPENAI_API_KEY environment variable is not set. "
                "Export it before running LLM commands:\n"
                "  export OPENAI_API_KEY='sk-...'"
            )
        self._client = OpenAI(api_key=api_key)
        self.model = model
        self.temperature = temperature

    def generate_text(self, system: str, user: str) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        choice = response.choices[0]
        return choice.message.content or ""
