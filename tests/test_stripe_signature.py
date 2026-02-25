"""Tests for Stripe webhook signature verification."""

import hmac
import hashlib
import time

import pytest

from app.utils.stripe_signature import verify_stripe_signature


def _make_valid_header(payload: bytes, secret: str, timestamp: str | None = None) -> str:
    """Build a valid Stripe-Signature header for testing."""
    if timestamp is None:
        timestamp = str(int(time.time()))
    signed = f"{timestamp}.{payload.decode('utf-8')}"
    sig = hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={sig}"


def test_verify_stripe_signature_valid():
    """Valid signature returns True."""
    payload = b'{"object":"event","type":"invoice.paid"}'
    secret = "whsec_test123"
    header = _make_valid_header(payload, secret)
    assert verify_stripe_signature(payload, header, secret) is True


def test_verify_stripe_signature_invalid_tampered_payload():
    """Tampered payload returns False."""
    payload = b'{"object":"event","type":"invoice.paid"}'
    secret = "whsec_test123"
    header = _make_valid_header(payload, secret)
    tampered = b'{"object":"event","type":"invoice.paid","tampered":true}'
    assert verify_stripe_signature(tampered, header, secret) is False


def test_verify_stripe_signature_invalid_wrong_secret():
    """Wrong secret returns False."""
    payload = b'{"object":"event"}'
    header = _make_valid_header(payload, "whsec_correct")
    assert verify_stripe_signature(payload, header, "whsec_wrong") is False


def test_verify_stripe_signature_missing_header():
    """Missing header returns False."""
    assert verify_stripe_signature(b"{}", None, "whsec_x") is False


def test_verify_stripe_signature_missing_secret():
    """Empty secret returns False."""
    payload = b"{}"
    header = _make_valid_header(payload, "whsec_x")
    assert verify_stripe_signature(payload, header, "") is False


def test_verify_stripe_signature_expired_timestamp():
    """Signature with old timestamp is rejected."""
    payload = b'{"object":"event"}'
    secret = "whsec_test123"
    old_timestamp = str(int(time.time()) - 600)  # 10 minutes ago
    header = _make_valid_header(payload, secret, timestamp=old_timestamp)
    assert verify_stripe_signature(payload, header, secret) is False
