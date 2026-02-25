"""Tests for Adyen webhook HMAC verification."""

import base64
import binascii
import hmac
import hashlib

import pytest

from app.utils.adyen_signature import verify_adyen_signature


def _make_adyen_hmac(item: dict, key_hex: str) -> str:
    """Build HMAC for a NotificationRequestItem (same algorithm as Adyen)."""
    key_bytes = binascii.a2b_hex(key_hex.strip())
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
    return base64.b64encode(
        hmac.new(key_bytes, signing_string.encode("utf-8"), hashlib.sha256).digest()
    ).decode("utf-8")


# Example from Adyen docs (key and payload with valid signature)
ADYEN_DOCS_KEY = "44782DEF547AAA06C910C43932B1EB0C71FC68D9D0C057550C48EC2ACF6BA056"
ADYEN_DOCS_ITEM = {
    "additionalData": {"hmacSignature": "coqCmt/IZ4E3CzPvMY8zTjQVL5hYJUiBRg8UU+iCWo0="},
    "amount": {"value": 1130, "currency": "EUR"},
    "pspReference": "7914073381342284",
    "eventCode": "AUTHORISATION",
    "eventDate": "2019-05-06T17:15:34.121+02:00",
    "merchantAccountCode": "TestMerchant",
    "merchantReference": "TestPayment-1407325143704",
    "paymentMethod": "visa",
    "success": "true",
}


def test_verify_adyen_signature_valid():
    """Valid signature (doc example) returns True."""
    wrapper = {"NotificationRequestItem": ADYEN_DOCS_ITEM}
    assert verify_adyen_signature(wrapper, ADYEN_DOCS_KEY) is True


def test_verify_adyen_signature_inner_item():
    """Passing inner item dict (no wrapper) also works."""
    assert verify_adyen_signature(ADYEN_DOCS_ITEM, ADYEN_DOCS_KEY) is True


def test_verify_adyen_signature_invalid_wrong_key():
    """Wrong HMAC key returns False."""
    wrapper = {"NotificationRequestItem": ADYEN_DOCS_ITEM}
    assert verify_adyen_signature(wrapper, "00" * 32) is False


def test_verify_adyen_signature_invalid_tampered():
    """Tampered amount returns False."""
    tampered = dict(ADYEN_DOCS_ITEM)
    tampered["amount"] = {"value": 9999, "currency": "EUR"}
    tampered["additionalData"] = {"hmacSignature": _make_adyen_hmac(ADYEN_DOCS_ITEM, ADYEN_DOCS_KEY)}
    wrapper = {"NotificationRequestItem": tampered}
    # Our recompute uses tampered amount so we'd get different sig - old sig won't match
    assert verify_adyen_signature(wrapper, ADYEN_DOCS_KEY) is False


def test_verify_adyen_signature_missing_header():
    """Missing hmacSignature returns False."""
    item = dict(ADYEN_DOCS_ITEM)
    item["additionalData"] = {}
    assert verify_adyen_signature({"NotificationRequestItem": item}, ADYEN_DOCS_KEY) is False


def test_verify_adyen_signature_missing_key():
    """Empty key returns False."""
    assert verify_adyen_signature({"NotificationRequestItem": ADYEN_DOCS_ITEM}, "") is False


def test_verify_adyen_signature_invalid_hex_key():
    """Invalid hex key returns False."""
    assert verify_adyen_signature({"NotificationRequestItem": ADYEN_DOCS_ITEM}, "nothex") is False
