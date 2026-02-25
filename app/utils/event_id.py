"""Derive a stable, provider-scoped event id for idempotency.

Uses provider-native keys (not X-Idempotency-Key or canonical JSON hash) so
deduplication holds across payload styles and provider retries.
"""

import hashlib
import json

# Max length for event_id stored in DB (unique constraint).
EVENT_ID_MAX_LEN = 256


def canonical_json(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def derive_event_id(source: str, body: dict) -> str:
    """
    Derive a stable event id for deduplication from provider and body.

    - Stripe: stripe:{event.id} (e.g. stripe:evt_123)
    - PayPal: paypal:{webhook_event.id} (e.g. paypal:WH-xxx or paypal:8PT...)
    - Adyen: adyen:{eventCode}:{pspReference} (duplicates share same eventCode+pspReference)
    - unknown: sha256(canonical_json(body)) as fallback
    """
    if not isinstance(body, dict):
        raw = canonical_json({"unknown": True}).encode()
        return hashlib.sha256(raw).hexdigest()[:EVENT_ID_MAX_LEN]

    if source == "stripe":
        event_id = body.get("id")
        if event_id:
            key = f"stripe:{event_id}"
            return key[:EVENT_ID_MAX_LEN]
    elif source == "paypal":
        event_id = body.get("id") or body.get("event_id")
        if event_id:
            key = f"paypal:{event_id}"
            return key[:EVENT_ID_MAX_LEN]
    elif source == "adyen":
        items = body.get("notificationItems")
        if isinstance(items, list) and len(items) > 0:
            first = items[0]
            item = first.get("NotificationRequestItem") if isinstance(first, dict) else first
            if isinstance(item, dict):
                event_code = item.get("eventCode") or ""
                psp_ref = item.get("pspReference") or ""
                if event_code or psp_ref:
                    key = f"adyen:{event_code}:{psp_ref}"
                    return key[:EVENT_ID_MAX_LEN]

    # Unknown or missing provider keys: fallback to hash
    raw = canonical_json(body).encode()
    return hashlib.sha256(raw).hexdigest()[:EVENT_ID_MAX_LEN]
