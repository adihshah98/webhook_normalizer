"""Verify Stripe webhook signatures (Stripe-Signature header)."""

import hmac
import hashlib
import time

# Maximum age of a signature before it's rejected (seconds).
# Stripe's own library uses 300s (5 minutes).
DEFAULT_TOLERANCE_SECONDS = 300


def verify_stripe_signature(
    payload: bytes,
    signature_header: str | None,
    secret: str,
    tolerance: int = DEFAULT_TOLERANCE_SECONDS,
) -> bool:
    """
    Verify that the webhook payload was sent by Stripe.

    Args:
        payload: Raw request body (bytes).
        signature_header: Value of the Stripe-Signature header.
        secret: Webhook signing secret (whsec_...).
        tolerance: Max allowed age of the signature in seconds (default 300).

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

        # Reject signatures that are too old (replay protection)
        if abs(time.time() - int(timestamp)) > tolerance:
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
