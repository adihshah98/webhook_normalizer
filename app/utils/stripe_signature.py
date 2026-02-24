"""Verify Stripe webhook signatures (Stripe-Signature header)."""

import hmac
import hashlib


def verify_stripe_signature(
    payload: bytes,
    signature_header: str | None,
    secret: str,
) -> bool:
    """
    Verify that the webhook payload was sent by Stripe.

    Args:
        payload: Raw request body (bytes).
        signature_header: Value of the Stripe-Signature header.
        secret: Webhook signing secret (whsec_...).

    Returns:
        True if the signature is valid, False otherwise.
    """
    if not signature_header or not secret:
        return False

    try:
        parts = signature_header.split(",")
        timestamp = None
        v1_sig = None
        for part in parts:
            part = part.strip()
            if part.startswith("t="):
                timestamp = part[2:]
            elif part.startswith("v1="):
                v1_sig = part[3:]
        if not timestamp or not v1_sig:
            return False

        signed_payload = f"{timestamp}.{payload.decode('utf-8')}"
        expected = hmac.new(
            secret.encode("utf-8"),
            signed_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(f"v1={expected}", f"v1={v1_sig}")
    except Exception:
        return False
