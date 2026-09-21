import os
import sys
from pathlib import Path

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Load server/.env FIRST so live tests see the real key. Only then fall back to a
# dummy, which is enough to get the offline suite past the has_api_key() guard.
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")

SAMPLES = ROOT.parent / "samples"


# --- model doubles -------------------------------------------------------- #
# Production uses Anthropic structured outputs (`NativeOutput`), so the double has
# to speak that too. `TestModel` cannot: its `_get_output` indexes
# `output_tools[0]`, which only exists in tool mode. `FunctionModel` lets us return
# the JSON as a text part, exactly as native mode delivers it.
import json  # noqa: E402

from pydantic_ai.messages import ModelResponse, TextPart  # noqa: E402
from pydantic_ai.models.function import FunctionModel  # noqa: E402
from pydantic_ai.profiles import ModelProfile  # noqa: E402

NATIVE_PROFILE = ModelProfile(
    supports_json_schema_output=True,
    default_structured_output_mode="native",
)


def stub_model(payload: dict) -> FunctionModel:
    """A model double returning `payload` the way native structured output does."""

    async def fn(messages, info):
        return ModelResponse(parts=[TextPart(json.dumps(payload))])

    return FunctionModel(fn, profile=NATIVE_PROFILE)


def failing_model(exc: Exception) -> FunctionModel:
    """A model double that blows up, for degradation paths."""

    async def fn(messages, info):
        raise exc

    return FunctionModel(fn, profile=NATIVE_PROFILE)
