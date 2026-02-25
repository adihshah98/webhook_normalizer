"""Verify Adyen Standard webhook HMAC (additionalData.hmacSignature)."""

import base64
import binascii
import hmac
import hashlib


def verify_adyen_signature(
    notification_item: dict,
    hmac_key: str,
) -> bool:
    """
    Verify that a single Adyen NotificationRequestItem was signed by Adyen.

    Uses the same algorithm as Adyen docs: build payload from
    pspReference, originalReference, merchantAccountCode, merchantReference,
    value, currency, eventCode, success (colon-delimited); HMAC-SHA256 with
    hex-decoded key; Base64 compare with additionalData.hmacSignature.

    Args:
        notification_item: One NotificationRequestItem dict (the inner object).
        hmac_key: HMAC key from Customer Area (hex string).

    Returns:
        True if the signature is valid, False otherwise.
    """
    if not hmac_key or not notification_item:
        return False

    item = notification_item.get("NotificationRequestItem") if isinstance(
        notification_item.get("NotificationRequestItem"), dict
    ) else notification_item
    if not isinstance(item, dict):
        return False

    additional = item.get("additionalData") or {}
    received_sig = additional.get("hmacSignature") if isinstance(additional, dict) else None
    if not received_sig:
        return False

    try:
        key_bytes = binascii.a2b_hex(hmac_key.strip())
    except (binascii.Error, ValueError):
        return False

    # Build a flat dict for signing: value/currency from amount
    request_dict = dict(item)
    request_dict.pop("additionalData", None)
    amount = request_dict.get("amount")
    if isinstance(amount, dict):
        request_dict["value"] = amount.get("value", "")
        request_dict["currency"] = amount.get("currency", "")
    else:
        request_dict["value"] = ""
        request_dict["currency"] = ""

    element_orders = [
        "pspReference",
        "originalReference",
        "merchantAccountCode",
        "merchantReference",
        "value",
        "currency",
        "eventCode",
        "success",
    ]
    signing_string = ":".join(str(request_dict.get(el, "")) for el in element_orders)
    expected = base64.b64encode(
        hmac.new(key_bytes, signing_string.encode("utf-8"), hashlib.sha256).digest()
    ).decode("utf-8")

    return hmac.compare_digest(expected, received_sig)
