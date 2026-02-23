from typing import Any, Literal

from pydantic import BaseModel


class WebhookOut(BaseModel):
    """Webhook response - single format for all statuses."""

    status: Literal["created", "duplicate", "invalid"]
    event_id: str | None = None
    standardized: dict[str, Any] | None = None
    dlq: bool = False
    reason: str | None = None
