"""Shared prompt and strict label parser for automatic thinking selection."""

import json

THINKING_CLASSIFIER_PROMPT = (
    "Classify whether the request needs extended reasoning. Set thinking to 'on' "
    "for multi-step, ambiguous, analytical, or code-related work; otherwise set it "
    "to 'off'. Return only the requested JSON object."
)
THINKING_CLASSIFIER_SCHEMA = {
    "type": "object",
    "properties": {"thinking": {"type": "string", "enum": ["on", "off"]}},
    "required": ["thinking"],
    "additionalProperties": False,
}


def parse_thinking_label(value: object) -> bool | None:
    if not isinstance(value, str):
        return None
    label = value.strip().lower()
    if label.startswith("{"):
        try:
            result = json.loads(label)
        except json.JSONDecodeError:
            return None
        if not isinstance(result, dict) or set(result) != {"thinking"}:
            return None
        label = result["thinking"]
        if not isinstance(label, str):
            return None
        label = label.strip().lower()
    if label == "on":
        return True
    if label == "off":
        return False
    return None
