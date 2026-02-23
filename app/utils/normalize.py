"""Standardize webhook payloads from various sources into a canonical format."""

from typing import Callable

Normalizer = Callable[[dict], dict]


def _canonical(event_id: str, source: str, raw: dict, **overrides) -> dict:
    """Build standardized output with common fields."""
    return {
        "event_id": event_id,
        "source": source,
        "raw": raw,
        **overrides,
    }


def normalize_crm(raw: dict) -> dict:
    """CRM-style: event_type, account, contact, metadata."""
    account = raw.get("account") or {}
    contact = raw.get("contact") or {}
    event_type = raw.get("event_type", "")
    entity_type = event_type.split(".")[0] if event_type else ""
    entity_id = contact.get("id") or account.get("id") or ""
    customer_id = account.get("id", "")
    payload = {k: v for k, v in contact.items() if k != "id"} if contact else {}
    return {
        "customer_id": customer_id,
        "event_type": event_type,
        "occurred_at": raw.get("occurred_at"),
        "entity_type": entity_type,
        "entity_id": entity_id,
        "payload": payload,
    }


def normalize_billing(raw: dict) -> dict:
    """Billing-style: type, data.object, customer_id (e.g. Stripe-like)."""
    data = raw.get("data") or {}
    obj = data.get("object") or raw
    event_type = raw.get("type", "")
    entity_type = event_type.split(".")[0] if event_type else "unknown"
    return {
        "customer_id": raw.get("customer_id", obj.get("customer_id", "")),
        "event_type": event_type,
        "occurred_at": raw.get("created") or raw.get("occurred_at"),
        "entity_type": entity_type,
        "entity_id": str(obj.get("id", "")),
        "payload": {k: v for k, v in obj.items() if k not in ("id", "customer_id")},
    }


NORMALIZERS: dict[str, Normalizer] = {
    "crm": normalize_crm,
    "billing": normalize_billing,
}


def _detect_format(raw: dict) -> str:
    """Guess format from structure. Falls back to 'crm'."""
    if isinstance(raw.get("data"), dict) and "object" in (raw.get("data") or {}):
        return "billing"
    if "account" in raw or "contact" in raw:
        return "crm"
    return "crm"


def normalize_webhook(raw: dict, event_id: str) -> dict:
    """
    Map inbound webhook to standardized output.
    Detects format from payload structure (crm vs billing).
    """
    fmt = _detect_format(raw)
    normalizer = NORMALIZERS.get(fmt, normalize_crm)
    fields = normalizer(raw)
    return _canonical(event_id, fmt, raw, **fields)
