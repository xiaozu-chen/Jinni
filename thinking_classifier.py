"""Shared prompt and strict label parser for automatic thinking selection."""

THINKING_CLASSIFIER_PROMPT = (
    "Classify whether the request needs extended reasoning. "
    "Reply with exactly 'on' for multi-step, ambiguous, analytical, "
    "or code-related work; otherwise reply with exactly 'off'."
)


def parse_thinking_label(value: object) -> bool | None:
    if not isinstance(value, str):
        return None
    label = value.strip().lower()
    if label == "on":
        return True
    if label == "off":
        return False
    return None
