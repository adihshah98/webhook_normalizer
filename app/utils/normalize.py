"""Standardize webhook payloads (Stripe, Adyen) into a common canonical format.

Stored/API output shape: only event_id, source, extracted, raw.
- event_id, source: top-level.
- extracted: object with canonical fields (provider_event_id, event_type, entity_type,
  occurred_at, customer_id, amount, success, merchant_account, reference, livemode,
  payer_email, payment_method_type, description, metadata, idempotency_key,
  refund_id, refund_amount, original_provider_id). See docs/SCHEMA.md.
- raw: full inbound webhook body.
"""

from typing import Any, Callable

Normalizer = Callable[[dict], dict]

# Canonical extracted field keys (all normalizers return a dict with these keys)
EXTRACTED_KEYS = (
    "provider_event_id",
    "event_type",
    "entity_type",
    "occurred_at",
    "customer_id",
    "amount",
    "success",
    "merchant_account",
    "reference",
    "livemode",
    "payer_email",
    "payment_method_type",
    "description",
    "metadata",
    "idempotency_key",
    "refund_id",
    "refund_amount",
    "original_provider_id",
)


def _canonical(event_id: str, source: str, raw: dict, extracted: dict) -> dict:
    """Build standardized output: only event_id, source, extracted, raw."""
    return {
        "event_id": event_id,
        "source": source,
        "extracted": extracted,
        "raw": raw,
    }


def _get_nested(obj: dict, path: str, default=None):
    """Safely get a nested value using dot notation."""
    for k in path.split("."):
        if not isinstance(obj, dict) or k not in obj:
            return default
        obj = obj[k]
    return obj


def _extract_stripe_amount(obj: dict) -> dict[str, Any] | None:
    """Extract { value, currency } from Stripe object. Value in minor units."""
    value = obj.get("amount") or obj.get("amount_due") or obj.get("amount_paid") or obj.get("amount_received")
    if value is None:
        return None
    currency = obj.get("currency") or _get_nested(obj, "amount.currency")
    if currency is None:
        return {"value": value, "currency": ""}
    return {"value": value, "currency": str(currency).upper()}


def _infer_stripe_success(obj: dict, event_type: str) -> bool | None:
    """Infer success from Stripe object status. None when unclear."""
    status = obj.get("status")
    if status is None:
        return None
    success_states = ("succeeded", "paid", "complete", "active")
    if status in success_states:
        return True
    failed_states = ("failed", "canceled", "cancelled", "refunded")
    if status in failed_states:
        return False
    return None


def _extract_stripe_payer_email(obj: dict, event_type: str) -> str:
    """Payer email from customer_details, billing_details, receipt_email, or Customer email."""
    email = (
        _get_nested(obj, "customer_details.email")
        or _get_nested(obj, "billing_details.email")
        or obj.get("receipt_email")
    )
    if email:
        return str(email)
    # customer.* events: obj is Customer, has email
    if event_type.startswith("customer.") and isinstance(obj.get("email"), str):
        return obj["email"]
    return ""


def _extract_stripe_payment_method_type(obj: dict) -> str:
    """Payment method type from payment_method_details or payment_method_types."""
    details = obj.get("payment_method_details") or {}
    if isinstance(details, dict) and details.get("type"):
        return str(details["type"])
    types = obj.get("payment_method_types")
    if isinstance(types, list) and len(types) > 0:
        return str(types[0])
    return ""


def _empty_extracted() -> dict:
    """Base extracted dict with all keys set to empty/null defaults."""
    return {
        "provider_event_id": "",
        "event_type": "",
        "entity_type": "unknown",
        "occurred_at": None,
        "customer_id": "",
        "amount": None,
        "success": None,
        "merchant_account": "",
        "reference": "",
        "livemode": None,
        "payer_email": "",
        "payment_method_type": "",
        "description": "",
        "metadata": {},
        "idempotency_key": "",
        "refund_id": "",
        "refund_amount": None,
        "original_provider_id": "",
    }


# --- Stripe ---


def normalize_stripe(raw: dict) -> dict:
    """Stripe Event: extract canonical fields into a single dict (no payload, no raw)."""
    data = raw.get("data") or {}
    obj = data.get("object") or {}
    event_type = raw.get("type", "")
    # Use data.object type when it's a refund so charge.refunded -> entity_type "refund"
    obj_type = obj.get("object") if isinstance(obj.get("object"), str) else ""
    entity_type = obj_type if obj_type == "refund" else (event_type.split(".")[0] if event_type else "unknown")

    out = _empty_extracted()

    out["provider_event_id"] = str(obj.get("id", ""))
    out["event_type"] = event_type
    out["entity_type"] = entity_type
    out["occurred_at"] = raw.get("created")
    out["amount"] = _extract_stripe_amount(obj)
    out["success"] = _infer_stripe_success(obj, event_type)
    out["merchant_account"] = str(raw.get("account") or "")
    meta = obj.get("metadata") or {}
    out["reference"] = str(meta.get("order_id") or meta.get("reference") or "")

    out["livemode"] = raw.get("livemode") if "livemode" in raw else None
    req = raw.get("request") or {}
    out["idempotency_key"] = str(req.get("idempotency_key") or "")

    # Customer id: for customer.* events the object is the Customer (use id); else customer ref or email
    if event_type.startswith("customer.") and obj.get("id"):
        out["customer_id"] = str(obj["id"])
    else:
        cust = obj.get("customer")
        if isinstance(cust, str):
            out["customer_id"] = cust
        elif isinstance(cust, dict) and cust.get("id"):
            out["customer_id"] = cust["id"]
        else:
            out["customer_id"] = _get_nested(obj, "customer_details.email") or ""

    out["payer_email"] = _extract_stripe_payer_email(obj, event_type)
    out["payment_method_type"] = _extract_stripe_payment_method_type(obj)
    out["description"] = str(obj.get("description") or "")
    out["metadata"] = dict(meta) if isinstance(meta, dict) else {}

    # Refunds
    if entity_type == "refund":
        out["refund_id"] = str(obj.get("id", ""))
        out["refund_amount"] = _extract_stripe_amount(obj)
        out["original_provider_id"] = str(obj.get("charge") or obj.get("payment_intent") or "")
    else:
        # Charge with refunds: optional refund_amount from first refund if needed; original_provider_id for linking
        pass

    return out


# --- Fallback ---


def _normalize_unknown(raw: dict) -> dict:
    """Minimal extracted fields when provider cannot be detected."""
    out = _empty_extracted()
    out["event_type"] = str(raw.get("type") or raw.get("event_type") or "")
    out["occurred_at"] = raw.get("created") or raw.get("create_time") or raw.get("occurred_at")
    return out


# --- Detection & dispatch ---

NORMALIZERS: dict[str, Normalizer] = {
    "stripe": normalize_stripe,
}


def _detect_source(raw: dict) -> str:
    """Detect Stripe Event from payload structure."""
    if not isinstance(raw, dict):
        return "unknown"
    if raw.get("object") == "event":
        data = raw.get("data")
        if isinstance(data, dict) and "object" in data:
            return "stripe"
    return "unknown"


def normalize_webhook(raw: dict, event_id: str) -> dict:
    """
    Map inbound webhook to standardized output.
    Top-level keys only: event_id, source, extracted, raw.
    """
    source = _detect_source(raw)
    if source == "unknown":
        extracted = _normalize_unknown(raw)
    else:
        extracted = NORMALIZERS[source](raw)
    return _canonical(event_id, source, raw, extracted)
