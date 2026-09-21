"""Model-call construction and the shared user-turn builder.

Naming is deliberate. `classifier` and `extractor` are SINGLE constrained model
calls — no tools, no loop. They are built with PydanticAI's `Agent` class only
because that is the library's entry point for schema-validated output with repair
retries; it is not an architectural claim. `resolve_agent` keeps the name because
it is the only one that is genuinely agentic: it has tools and model-driven
control flow.

Agents are built once at import and reused: instructions are static, which keeps
them cacheable and keeps per-request work to the varying content only.

`defer_model_check=True` matters — without it, constructing an Agent resolves the
provider eagerly and raises if ANTHROPIC_API_KEY is unset, so the service could
not even boot without a key. The spec asks that the rest of the service still run
in that case, so the key is checked at call time and reported as a clean
contract-shaped result instead.
"""
from __future__ import annotations

import os

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from pydantic_ai import Agent, BinaryContent, NativeOutput  # noqa: E402
from pydantic_ai.models.anthropic import AnthropicModelSettings  # noqa: E402

from ..config import MODEL  # noqa: E402
from ..ingest.source import RenderedSource  # noqa: E402
from ..prompts import (  # noqa: E402
    CLASSIFY_INSTRUCTIONS,
    EXTRACT_INSTRUCTIONS,
    RESOLVE_INSTRUCTIONS,
    wrap_untrusted,
)
from .models import Classification, Extraction, Resolution  # noqa: E402

# PydanticAI's schema-repair loop: on a ValidationError the error is fed back to
# the model for a corrected attempt.
_RETRIES = 2

# Effort is tuned per stage, measured rather than guessed. Extraction is the only
# intelligence-sensitive step; classification is a simple binary call and resolution
# is rule-application. max_tokens must cover thinking + output, since thinking is on
# by default on Opus 5.
_CLASSIFY_SETTINGS = AnthropicModelSettings(max_tokens=8_000, anthropic_effort="low")
_EXTRACT_SETTINGS = AnthropicModelSettings(max_tokens=32_000, anthropic_effort="high")
# Resolve is mechanical rule-application (map candidates to catalogue results,
# apply the quantity rules), not deep reasoning. Measured at "high" it was 247s of
# a 257s request — 96% of total latency. "low" does the same job in a fraction of
# the time; raise it only if resolution quality regresses.
_RESOLVE_SETTINGS = AnthropicModelSettings(max_tokens=16_000, anthropic_effort="low")


def _model_call(output_type, instructions, settings, name):
    """Build a call that returns `output_type`, using Anthropic structured outputs.

    `NativeOutput` sends the schema as `output_config.format` (json_schema, with
    `additionalProperties: false` and `required` populated) so decoding is
    constrained to the schema. The alternative — PydanticAI's default `tool` mode
    for Anthropic — declares a synthetic `final_result` tool and does NOT set
    `strict`, which makes the schema a hint enforced only by Pydantic afterwards.

    Two reasons native wins here:
      * Stronger conformance: constrained generation rather than validate-and-retry.
      * For `resolve_agent` it keeps the tool list to the two REAL tools. In tool
        mode the model picks from a menu where "stop and answer" (`final_result`)
        sits beside "go look something up", which invites terminating early.
    """
    return Agent(
        MODEL,
        output_type=NativeOutput(output_type),
        instructions=instructions,
        model_settings=settings,
        retries=_RETRIES,
        defer_model_check=True,
        name=name,
    )


# Single constrained model calls — not agents.
classifier = _model_call(Classification, CLASSIFY_INSTRUCTIONS, _CLASSIFY_SETTINGS, "classify")
extractor = _model_call(Extraction, EXTRACT_INSTRUCTIONS, _EXTRACT_SETTINGS, "extract")

# Genuinely agentic: has tools (see tools.py) and loops until done.
resolve_agent = _model_call(Resolution, RESOLVE_INSTRUCTIONS, _RESOLVE_SETTINGS, "resolve")


def build_user_content(
    rendered: RenderedSource,
    *,
    sent_date: str | None,
    text: str | None = None,
) -> list:
    """Assemble the user turn: untrusted text plus any images.

    The date anchor sits OUTSIDE the untrusted tags — it is our own metadata,
    not something the email is allowed to influence.
    """
    anchor = (
        f"The email was sent on {sent_date}. Resolve any relative dates against that date."
        if sent_date
        else "The email has no usable sent date; do not guess at relative dates."
    )
    body = text if text is not None else rendered.combined_text()
    content: list = [anchor, wrap_untrusted(body)]
    for data, media_type in rendered.images:
        content.append(BinaryContent(data=data, media_type=media_type))
    return content
