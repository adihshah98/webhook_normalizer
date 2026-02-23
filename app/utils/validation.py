"""Validation helpers."""


def validate_webhook_body(body: dict) -> str | None:
    """Returns None if valid, else reason string."""
    if not isinstance(body, dict):
        return "payload must be object"
    if not body:
        return "payload must be non-empty"
    return None
