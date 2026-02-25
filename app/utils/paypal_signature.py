"""Verify PayPal webhook signatures (RSA-SHA256 with transmission headers + CRC32)."""

import base64
import zlib
import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

# Simple in-memory cert cache (url -> PEM string)
_cert_cache: dict[str, str] = {}


def verify_paypal_signature(
    raw_body: bytes,
    transmission_id: str | None,
    transmission_time: str | None,
    transmission_sig: str | None,
    cert_url: str | None,
    webhook_id: str,
) -> bool:
    """
    Verify that a PayPal webhook payload was sent by PayPal.

    Uses self-cryptographic verification: build message from
    transmissionId|timeStamp|webhookId|crc32, then verify RSA-SHA256
    signature using the public cert from paypal-cert-url.

    Args:
        raw_body: Raw HTTP request body (bytes). Must not be parsed/re-serialized.
        transmission_id: paypal-transmission-id header.
        transmission_time: paypal-transmission-time header.
        transmission_sig: paypal-transmission-sig header (base64).
        cert_url: paypal-cert-url header (URL to PEM cert).
        webhook_id: Webhook ID from your subscription (PAYPAL_WEBHOOK_ID).

    Returns:
        True if the signature is valid, False otherwise.
    """
    if not all((transmission_id, transmission_time, transmission_sig, cert_url, webhook_id)):
        return False

    try:
        # 1. Rebuild the exact string PayPal signed: transmissionId|timeStamp|webhookId|crc32
        body_crc32_unsigned = zlib.crc32(raw_body) & 0xFFFFFFFF  # Python's crc32 is signed; mask to unsigned
        signed_message = f"{transmission_id}|{transmission_time}|{webhook_id}|{body_crc32_unsigned}"

        # 2. Decode the base64 signature from the header
        signature_bytes = base64.b64decode(transmission_sig)

        # 3. Load PayPal's public cert and verify the signature (RSA-SHA256)
        cert_pem = _get_cert(cert_url)
        cert = x509.load_pem_x509_certificate(cert_pem.encode("utf-8"))
        public_key = cert.public_key()
        public_key.verify(
            signature_bytes,
            signed_message.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except Exception:
        return False


def _get_cert(url: str) -> str:
    """Fetch PEM cert from URL, with simple in-memory cache."""
    if url in _cert_cache:
        return _cert_cache[url]
    with httpx.Client() as client:
        resp = client.get(url, timeout=10.0)
        resp.raise_for_status()
        pem = resp.text
    _cert_cache[url] = pem
    return pem
