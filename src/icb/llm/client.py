"""One structured-output call to Claude (CLAUDE.md §4, model conventions).

Conventions kept here so both the criteria build and the screening use them:
streamed (outputs can be long), `claude-opus-5` by default, adaptive thinking, effort from
config, and no `temperature` / `top_p` / `budget_tokens` — this model rejects them.

The result is parsed from the response text against the caller's JSON schema, which the API
enforces via `output_config.format`. If the caller's own validation still fails, the call is
retried once with the error appended as a correction turn, then it fails loudly.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import anthropic

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_EFFORT = "high"
MAX_TOKENS = 32_000  # streamed, so no HTTP-timeout concern


class ModelError(RuntimeError):
    """The model could not be called, or did not return usable output."""


@dataclass(frozen=True)
class ModelResult:
    data: dict[str, Any]
    model: str
    input_tokens: int
    output_tokens: int
    corrected: bool

    @property
    def usage(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "corrected": self.corrected,
        }


def model_name() -> str:
    return os.getenv("ICB_MODEL") or DEFAULT_MODEL


def effort() -> str:
    return os.getenv("ICB_EFFORT") or DEFAULT_EFFORT


def build_client() -> anthropic.Anthropic:
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise ModelError("No Anthropic API key is configured on this server.")
    return anthropic.Anthropic()


def key_is_valid(client: anthropic.Anthropic | None = None) -> bool:
    """Costs no tokens: the models endpoint only checks the credential."""
    try:
        (client or build_client()).models.list(limit=1)
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, ModelError):
        return False
    return True


def _text_of(message: Any) -> str:
    return "".join(block.text for block in message.content if block.type == "text").strip()


def call_json(
    *,
    system: str,
    content: Sequence[dict[str, Any]],
    schema: dict[str, Any],
    schema_name: str,
    validate: Callable[[dict[str, Any]], Any] | None = None,
    client: anthropic.Anthropic | None = None,
    on_progress: Callable[[], None] | None = None,
) -> ModelResult:
    """Ask for one JSON document shaped by `schema`; return it parsed and validated."""
    client = client or build_client()
    messages: list[dict[str, Any]] = [{"role": "user", "content": list(content)}]
    corrected = False

    for attempt in (1, 2):
        try:
            with client.messages.stream(
                model=model_name(),
                max_tokens=MAX_TOKENS,
                system=system,
                messages=messages,
                thinking={"type": "adaptive"},
                output_config={
                    "effort": effort(),
                    "format": {"type": "json_schema", "name": schema_name, "schema": schema},
                },
            ) as stream:
                for _ in stream.text_stream:
                    if on_progress:
                        on_progress()
                message = stream.get_final_message()
        except anthropic.APIStatusError as exc:  # the SDK already retried 429/5xx
            raise ModelError(f"The Claude API returned an error ({exc.status_code}).") from exc
        except anthropic.APIConnectionError as exc:
            raise ModelError("The Claude API could not be reached.") from exc

        if message.stop_reason == "refusal":
            raise ModelError("The model declined this request.")
        if message.stop_reason == "max_tokens":
            raise ModelError("The model's answer was cut off. Try again with a smaller input.")

        raw = _text_of(message)
        problem: str | None = None
        try:
            data = json.loads(raw)
        except ValueError:
            data, problem = {}, "The response was not valid JSON."
        if problem is None and validate is not None:
            try:
                validate(data)
            except Exception as exc:  # the caller's validator decides what is acceptable
                problem = str(exc)

        if problem is None:
            return ModelResult(
                data=data,
                model=message.model,
                input_tokens=message.usage.input_tokens,
                output_tokens=message.usage.output_tokens,
                corrected=corrected,
            )
        if attempt == 2:
            raise ModelError(f"The model's answer did not fit the required shape: {problem}")

        corrected = True
        messages += [
            {"role": "assistant", "content": raw or "(no output)"},
            {"role": "user", "content": f"That response was rejected: {problem}\n"
                                        "Return the corrected JSON document only."},
        ]

    raise ModelError("The model could not be called.")  # unreachable
