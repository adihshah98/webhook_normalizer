"""Standardize webhook payloads (Stripe, Adyen) into a common canonical format.

Stored/API output shape: only event_id, source, extracted, raw.
- event_id, source: top-level.
- extracted: object with canonical fields (provider_event_id, event_type, entity_type,
  canonical_event_type, canonical_payment_method, occurred_at, customer_id, amount,
  success, merchant_account, reference, livemode, payer_email, payment_method_type,
  description, metadata, idempotency_key, refund_id, refund_amount, original_provider_id).
  See docs/SCHEMA.md.
- raw: full inbound webhook body.
"""

from typing import Any, Callable

Normalizer = Callable[[dict], dict]

# Canonical extracted field keys (all normalizers return a dict with these keys)
EXTRACTED_KEYS = (
    "provider_event_id",
    "event_type",
    "entity_type",
    "canonical_event_type",
    "canonical_payment_method",
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
        "canonical_event_type": "other",
        "canonical_payment_method": "other",
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


# --- Canonical mappings (cross-provider) ---

# Canonical event types: same semantics across Stripe, Adyen, etc.
def _canonical_event_type_stripe(event_type: str, success: bool | None) -> str:
    """Map Stripe event type + success to canonical_event_type."""
    if not event_type:
        return "other"
    t = event_type.lower()
    if t == "charge.succeeded" or t == "payment_intent.succeeded":
        return "payment.captured"
    if t == "charge.refunded":
        return "payment.refunded"
    if t == "invoice.paid":
        return "invoice.paid"
    if t.startswith("customer.created"):
        return "customer.created"
    if t.startswith("customer.updated"):
        return "customer.updated"
    if t in ("charge.failed", "payment_intent.payment_failed"):
        return "payment.failed"
    if "refund" in t:
        return "payment.refunded"
    if t in ("charge.dispute.created", "charge.dispute.updated"):
        return "dispute"
    if t.startswith("charge.") and success is False:
        return "payment.failed"
    if t.startswith("payment_intent."):
        return "payment.captured" if success else "payment.failed"
    return "other"


def _canonical_event_type_adyen(event_code: str, success: bool | None) -> str:
    """Map Adyen eventCode + success to canonical_event_type."""
    if not event_code:
        return "other"
    code = event_code.upper()
    if code in ("AUTHORISATION", "AUTHORISE"):
        return "payment.failed" if success is False else "payment.authorised"
    if code == "CAPTURE":
        return "payment.failed" if success is False else "payment.captured"
    if code == "REFUND":
        return "payment.refunded"
    if code in ("CANCELLATION", "CANCEL_OR_REFUND"):
        return "payment.cancelled"
    return "other"


def _canonical_event_type_paypal(event_type: str, success: bool | None) -> str:
    """Map PayPal event_type + success to canonical_event_type."""
    if not event_type:
        return "other"
    t = event_type.upper()
    if "AUTHORIZATION.CREATED" in t:
        return "payment.failed" if success is False else "payment.authorised"
    if "CAPTURE.COMPLETED" in t or "SALE.COMPLETED" in t:
        return "payment.captured"
    if "CAPTURE.REFUNDED" in t or "CAPTURE.REVERSED" in t or "SALE.REFUNDED" in t or "SALE.REVERSED" in t:
        return "payment.refunded"
    if "REFUND." in t and "PENDING" not in t and "FAILED" not in t:
        return "payment.refunded"
    if "AUTHORIZATION.VOIDED" in t or "ORDER.CANCELLED" in t:
        return "payment.cancelled"
    if "CAPTURE.DECLINED" in t or "CAPTURE.DENIED" in t or "SALE.DENIED" in t:
        return "payment.failed"
    if "REFUND.FAILED" in t:
        return "payment.failed"
    if "INVOICE.PAID" in t:
        return "invoice.paid"
    if "DISPUTE." in t:
        return "dispute"
    return "other"


def _canonical_payment_method(payment_method_type: str) -> str:
    """Map provider payment_method_type to canonical: card, paypal, bank_transfer, other."""
    if not payment_method_type:
        return "other"
    pm = payment_method_type.lower().strip()
    # Card (Stripe: card, Adyen: visa, mc, amex, etc.)
    if pm in ("card", "visa", "mc", "mastercard", "amex", "american_express", "diners", "discover"):
        return "card"
    if pm == "paypal":
        return "paypal"
    # Bank / bank transfer
    if pm in ("us_bank_account", "sepa_debit", "ideal", "sepa", "ach", "bank_transfer", "bank_transfer_iban"):
        return "bank_transfer"
    return "other"


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

    out["canonical_event_type"] = _canonical_event_type_stripe(event_type, out["success"])
    out["canonical_payment_method"] = _canonical_payment_method(out["payment_method_type"])

    # Refunds
    if entity_type == "refund":
        out["refund_id"] = str(obj.get("id", ""))
        out["refund_amount"] = _extract_stripe_amount(obj)
        out["original_provider_id"] = str(obj.get("charge") or obj.get("payment_intent") or "")
    else:
        # Charge with refunds: optional refund_amount from first refund if needed; original_provider_id for linking
        pass

    return out


# --- Adyen ---


def _extract_adyen_amount(item: dict) -> dict[str, Any] | None:
    """Extract { value, currency } from Adyen NotificationRequestItem. Value in minor units."""
    amount = item.get("amount")
    if not isinstance(amount, dict):
        return None
    value = amount.get("value")
    if value is None:
        return None
    currency = amount.get("currency") or ""
    return {"value": value, "currency": str(currency).upper()}


def _adyen_entity_type(event_code: str) -> str:
    """Map Adyen eventCode to canonical entity_type."""
    if not event_code:
        return "unknown"
    code = event_code.upper()
    if code == "REFUND":
        return "refund"
    if code in ("AUTHORISATION", "AUTHORISE", "CAPTURE", "CANCELLATION"):
        return "payment"
    return "payment"  # default for REPORT_AVAILABLE, etc.


def normalize_adyen(raw: dict) -> dict:
    """Adyen Standard webhook: use first notification item, extract canonical fields."""
    items = raw.get("notificationItems") or []
    if not items or not isinstance(items, list):
        return _empty_extracted()
    first = items[0]
    item = first.get("NotificationRequestItem") if isinstance(first, dict) else {}
    if not isinstance(item, dict):
        return _empty_extracted()

    event_code = str(item.get("eventCode") or "")
    out = _empty_extracted()

    out["provider_event_id"] = str(item.get("pspReference") or "")
    out["event_type"] = event_code
    out["entity_type"] = _adyen_entity_type(event_code)
    out["occurred_at"] = item.get("eventDate")
    out["amount"] = _extract_adyen_amount(item)
    success_val = item.get("success")
    out["success"] = bool(success_val) if success_val is not None else None
    out["merchant_account"] = str(item.get("merchantAccountCode") or "")
    out["reference"] = str(item.get("merchantReference") or "")
    live_str = raw.get("live")
    out["livemode"] = live_str == "true" if isinstance(live_str, str) else None

    additional = item.get("additionalData") or {}
    if isinstance(additional, dict):
        out["payer_email"] = str(additional.get("shopperEmail") or additional.get("email") or "")
        # Exclude hmacSignature from stored metadata
        out["metadata"] = {k: v for k, v in additional.items() if k != "hmacSignature"}
    else:
        out["payer_email"] = ""
        out["metadata"] = {}
    out["customer_id"] = str(additional.get("shopperReference", "")) if isinstance(additional, dict) else ""
    out["payment_method_type"] = str(item.get("paymentMethod") or "")
    out["description"] = str(item.get("reason") or "")

    out["canonical_event_type"] = _canonical_event_type_adyen(event_code, out["success"])
    out["canonical_payment_method"] = _canonical_payment_method(out["payment_method_type"])

    if out["entity_type"] == "refund":
        out["refund_id"] = str(item.get("pspReference") or "")
        out["refund_amount"] = _extract_adyen_amount(item)
        out["original_provider_id"] = str(item.get("originalReference") or "")

    return out


# --- PayPal ---


def _extract_paypal_amount(amount_obj: dict | None) -> dict[str, Any] | None:
    """Extract { value, currency } from PayPal amount. Value in minor units."""
    if not isinstance(amount_obj, dict):
        return None
    val = amount_obj.get("value")
    currency = str(amount_obj.get("currency_code") or amount_obj.get("currency") or "").upper()
    if val is None:
        return None
    try:
        fval = float(str(val))
    except (TypeError, ValueError):
        return None
    # Minor units: JPY/KRW etc have 0 decimals, most have 2
    decimals = 0 if currency in ("JPY", "KRW", "VND") else 2
    minor = int(round(fval * (10**decimals)))
    return {"value": minor, "currency": currency or ""}


def _paypal_entity_type(event_type: str, resource_type: str) -> str:
    """Map PayPal event_type + resource_type to canonical entity_type."""
    if not event_type:
        return "payment"
    t = event_type.upper()
    rt = (resource_type or "").upper()
    if "REFUND" in t or rt == "REFUND":
        return "refund"
    if "CAPTURE" in t or rt == "CAPTURE":
        return "payment"
    if "SALE" in t or rt == "SALE":
        return "payment"
    if "AUTHORIZATION" in t or rt == "AUTHORIZATION":
        return "payment"
    if "ORDER" in t or rt == "ORDER":
        return "order"
    if "INVOICE" in t:
        return "invoice"
    if "DISPUTE" in t:
        return "dispute"
    return "payment"


def normalize_paypal(raw: dict) -> dict:
    """PayPal webhook: extract canonical fields from event_type + resource."""
    resource = raw.get("resource") or {}
    if not isinstance(resource, dict):
        resource = {}
    event_type = str(raw.get("event_type") or "")
    resource_type = str(raw.get("resource_type") or "")

    out = _empty_extracted()

    out["provider_event_id"] = str(raw.get("id") or "")
    out["event_type"] = event_type
    out["entity_type"] = _paypal_entity_type(event_type, resource_type)
    out["occurred_at"] = raw.get("create_time")

    amount_obj = resource.get("amount") or resource.get("gross_amount")
    out["amount"] = _extract_paypal_amount(amount_obj)

    status = resource.get("status") or ""
    status_lower = status.lower()
    out["success"] = (
        True if status_lower in ("completed", "approved") else False if status_lower in ("declined", "denied", "failed", "voided") else None
    )

    payee = resource.get("payee") or {}
    if isinstance(payee, dict):
        out["merchant_account"] = str(payee.get("merchant_id") or payee.get("email_address") or "")
    else:
        out["merchant_account"] = ""

    related = (resource.get("supplementary_data") or {}).get("related_ids") or {}
    out["reference"] = str(related.get("order_id") or resource.get("custom_id") or resource.get("invoice_id") or "")

    out["payer_email"] = ""
    payer = resource.get("payer") or resource.get("billing_agreement_id")
    if isinstance(payer, dict):
        payer_info = payer.get("payer_info") or payer.get("email_address")
        if isinstance(payer_info, str):
            out["payer_email"] = payer_info
        elif isinstance(payer_info, dict) and payer_info.get("email"):
            out["payer_email"] = str(payer_info["email"])

    out["payment_method_type"] = "paypal"
    out["description"] = str(raw.get("summary") or "")
    out["metadata"] = {}
    out["livemode"] = None

    out["canonical_event_type"] = _canonical_event_type_paypal(event_type, out["success"])
    out["canonical_payment_method"] = "paypal"

    if out["entity_type"] == "refund":
        out["refund_id"] = str(resource.get("id") or raw.get("id") or "")
        out["refund_amount"] = _extract_paypal_amount(amount_obj)
        out["original_provider_id"] = str(resource.get("parent_payment") or related.get("capture_id") or "")

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
    "adyen": normalize_adyen,
    "paypal": normalize_paypal,
}


def _get_header(headers: dict | None, key: str) -> str | None:
    """Case-insensitive header lookup."""
    if not headers:
        return None
    key_lower = key.lower()
    for k, v in headers.items():
        if k.lower() == key_lower:
            return v
    return None


def _detect_source(raw: dict, headers: dict | None = None) -> str:
    """Detect provider: Stripe and PayPal from headers when present, else Adyen/unknown from body."""
    # Stripe and PayPal: use headers (they always send these when delivering webhooks)
    if headers is not None:
        if _get_header(headers, "Stripe-Signature"):
            return "stripe"
        if _get_header(headers, "paypal-transmission-id"):
            return "paypal"
    # Adyen and fallback: body-based (Adyen doesn't send a unique identifying header)
    if not isinstance(raw, dict):
        return "unknown"
    items = raw.get("notificationItems")
    if isinstance(items, list) and len(items) > 0:
        first = items[0]
        if isinstance(first, dict) and "NotificationRequestItem" in first:
            return "adyen"
    if raw.get("object") == "event":
        data = raw.get("data")
        if isinstance(data, dict) and "object" in data:
            return "stripe"
    if raw.get("event_type") and raw.get("id") and "create_time" in raw:
        return "paypal"
    if raw.get("eventType") and raw.get("id") and "createTime" in raw:
        return "paypal"
    return "unknown"


def detect_source(raw: dict, headers: dict | None = None) -> str:
    """Public: detect provider from headers then body. Used for idempotency key derivation."""
    return _detect_source(raw, headers)


def normalize_webhook(raw: dict, event_id: str, headers: dict | None = None) -> dict:
    """
    Map inbound webhook to standardized output.
    Top-level keys only: event_id, source, extracted, raw.
    When headers is provided, Stripe and PayPal are detected from headers; else from body.
    """
    source = _detect_source(raw, headers)
    if source == "unknown":
        extracted = _normalize_unknown(raw)
    else:
        extracted = NORMALIZERS[source](raw)
    return _canonical(event_id, source, raw, extracted)
