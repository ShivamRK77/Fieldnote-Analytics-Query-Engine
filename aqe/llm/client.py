"""Thin LLM abstraction so the planner is testable and provider-agnostic.
Structured output is obtained via forced tool-use (the model must call `submit_query_plan`)."""
from __future__ import annotations
import os
from typing import Protocol

TOOL = {
    "name": "submit_query_plan",
    "description": "Submit the interpretation and the SQLite query that answers the user's analytics question.",
    "input_schema": {
        "type": "object",
        "properties": {
            "answerable": {"type": "boolean", "description": "false if the question cannot be answered from the given tables"},
            "unanswerable_reason": {"type": "string"},
            "interpretation": {"type": "string", "description": "One or two sentences: what the user is asking, in business terms, with the metric definitions/filters/period you chose"},
            "sql": {"type": "string", "description": "A single read-only SQLite SELECT (or WITH ... SELECT) statement"},
            "assumptions": {"type": "array", "items": {"type": "string"}, "description": "Every interpretation choice you had to make that the question did not state"},
            "self_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["answerable", "interpretation", "sql", "assumptions", "self_confidence"],
    },
}


class LLMClient(Protocol):
    def plan(self, system: str, user: str) -> dict: ...


class LLMUnavailable(Exception):
    pass


class AnthropicClient:
    def __init__(self, model: str, max_tokens: int = 1500):
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise LLMUnavailable("ANTHROPIC_API_KEY is not set")
        try:
            import anthropic
        except ImportError as e:                      # pragma: no cover
            raise LLMUnavailable("the 'anthropic' package is not installed") from e
        self._client = anthropic.Anthropic()
        self.model, self.max_tokens = model, max_tokens

    def plan(self, system: str, user: str) -> dict:
        resp = self._client.messages.create(
            model=self.model, max_tokens=self.max_tokens, system=system,
            tools=[TOOL], tool_choice={"type": "tool", "name": TOOL["name"]},
            messages=[{"role": "user", "content": user}])
        for block in resp.content:
            if getattr(block, "type", "") == "tool_use":
                return dict(block.input)
        raise LLMUnavailable("model returned no tool call")


def default_client(model: str, max_tokens: int) -> AnthropicClient | None:
    try:
        return AnthropicClient(model, max_tokens)
    except LLMUnavailable:
        return None
