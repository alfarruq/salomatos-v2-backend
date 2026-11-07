"""The only place that talks to the language model.

Kept tiny on purpose so tests replace `extract` and the provider can change
without touching the form logic.
"""

import json
from dataclasses import dataclass

from django.conf import settings


class VoiceUnavailable(Exception):
    """No API key is configured, so the feature is off."""


class VoiceFailed(Exception):
    """The provider failed or declined; the caller shows a generic message."""


@dataclass
class Extraction:
    data: dict
    input_tokens: int
    output_tokens: int


def is_configured() -> bool:
    return bool(settings.ANTHROPIC_API_KEY)


def extract(system: str, text: str, schema: dict) -> Extraction:
    if not is_configured():
        raise VoiceUnavailable
    import anthropic

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, timeout=30.0, max_retries=1)
    try:
        response = client.messages.create(
            model=settings.VOICE_MODEL,
            max_tokens=4000,
            system=system,
            # Extraction is a simple task: low effort keeps it fast and cheap.
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": f"<dictation>\n{text}\n</dictation>"}],
        )
    except anthropic.APIError as error:
        # The exception text can echo the request; only its class is kept.
        raise VoiceFailed(type(error).__name__) from None
    if response.stop_reason != "end_turn":
        raise VoiceFailed(response.stop_reason or "unknown")
    body = next((block.text for block in response.content if block.type == "text"), "")
    try:
        data = json.loads(body)
    except ValueError:
        raise VoiceFailed("invalid_json") from None
    return Extraction(data, response.usage.input_tokens, response.usage.output_tokens)
