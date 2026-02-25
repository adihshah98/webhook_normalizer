"""Tests for PayPal webhook signature verification."""

import base64
import zlib
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from app.utils.paypal_signature import verify_paypal_signature


def _make_test_cert_and_key():
    """Generate a test RSA key pair and self-signed cert."""
    key = rsa.generate_private_key(65537, 2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COUNTRY_NAME, "US")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    return key, cert_pem


def test_verify_paypal_signature_valid():
    """Valid RSA-SHA256 signature returns True."""
    raw_body = b'{"id":"WH-123","event_type":"PAYMENT.CAPTURE.COMPLETED","create_time":"2024-01-01T00:00:00Z"}'
    transmission_id = "trans-123"
    transmission_time = "2024-01-01T00:00:00Z"
    webhook_id = "webhook-xyz"

    crc = zlib.crc32(raw_body) & 0xFFFFFFFF
    message = f"{transmission_id}|{transmission_time}|{webhook_id}|{crc}"

    key, cert_pem = _make_test_cert_and_key()
    signature = key.sign(message.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    transmission_sig = base64.b64encode(signature).decode()
    cert_url = "https://api.sandbox.paypal.com/v1/notifications/certs/test"

    with patch("app.utils.paypal_signature._get_cert", return_value=cert_pem):
        assert verify_paypal_signature(
            raw_body,
            transmission_id,
            transmission_time,
            transmission_sig,
            cert_url,
            webhook_id,
        ) is True


def test_verify_paypal_signature_invalid_wrong_sig():
    """Wrong signature returns False."""
    raw_body = b'{"id":"WH-123"}'
    transmission_id = "t1"
    transmission_time = "2024-01-01T00:00:00Z"
    webhook_id = "w1"
    cert_url = "https://example.com/cert"

    key, cert_pem = _make_test_cert_and_key()
    wrong_message = "wrong"
    signature = key.sign(wrong_message.encode(), padding.PKCS1v15(), hashes.SHA256())
    transmission_sig = base64.b64encode(signature).decode()

    with patch("app.utils.paypal_signature._get_cert", return_value=cert_pem):
        assert (
            verify_paypal_signature(
                raw_body,
                transmission_id,
                transmission_time,
                transmission_sig,
                cert_url,
                webhook_id,
            )
            is False
        )


def test_verify_paypal_signature_missing_headers():
    """Missing required headers returns False."""
    raw_body = b'{}'
    assert verify_paypal_signature(raw_body, None, "t", "sig", "url", "w1") is False
    assert verify_paypal_signature(raw_body, "tid", None, "sig", "url", "w1") is False
    assert verify_paypal_signature(raw_body, "tid", "t", None, "url", "w1") is False
    assert verify_paypal_signature(raw_body, "tid", "t", "sig", None, "w1") is False
    assert verify_paypal_signature(raw_body, "tid", "t", "sig", "url", "") is False


def test_verify_paypal_signature_mock_webhook_id():
    """Mock/simulated events use WEBHOOK_ID as webhook_id."""
    raw_body = b'{"id":"WH-mock"}'
    transmission_id = "mock-trans"
    transmission_time = "2024-01-01T00:00:00Z"
    webhook_id = "WEBHOOK_ID"
    cert_url = "https://example.com/cert"

    key, cert_pem = _make_test_cert_and_key()
    crc = zlib.crc32(raw_body) & 0xFFFFFFFF
    message = f"{transmission_id}|{transmission_time}|{webhook_id}|{crc}"
    signature = key.sign(message.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    transmission_sig = base64.b64encode(signature).decode()

    with patch("app.utils.paypal_signature._get_cert", return_value=cert_pem):
        assert verify_paypal_signature(
            raw_body, transmission_id, transmission_time, transmission_sig, cert_url, webhook_id
        ) is True
