import pytest

from app.utils.event_id import canonical_json, derive_event_id
from app.utils.normalize import normalize_webhook


def test_canonical_json():
    assert canonical_json({"a": 1, "b": 2}) == '{"a":1,"b":2}'


# --- Stripe ---


def test_normalize_webhook_stripe():
    """Stripe Event: output has only event_id, source, extracted, raw; canonical fields in extracted."""
    raw = {
        "id": "evt_1NG8Du2eZvKYlo2CUI79vXWy",
        "object": "event",
        "type": "invoice.paid",
        "created": 1686089970,
        "data": {
            "object": {
                "id": "in_1ABC123",
                "customer": "cus_xyz789",
                "amount_due": 1000,
                "currency": "usd",
                "status": "paid",
            }
        },
    }
    out = normalize_webhook(raw, event_id="ev_xyz")
    assert set(out.keys()) == {"event_id", "source", "extracted", "raw"}
    assert out["event_id"] == "ev_xyz"
    assert out["source"] == "stripe"
    assert out["raw"] == raw

    e = out["extracted"]
    assert e["provider_event_id"] == "in_1ABC123"
    assert e["event_type"] == "invoice.paid"
    assert e["entity_type"] == "invoice"
    assert e["customer_id"] == "cus_xyz789"
    assert e["occurred_at"] == 1686089970
    assert e["amount"] == {"value": 1000, "currency": "USD"}
    assert e["success"] is True
    assert e["merchant_account"] == ""
    assert e["reference"] == ""


def test_normalize_webhook_stripe_customer_from_customer_details():
    """Stripe: customer_id fallback to customer_details.email when no customer."""
    raw = {
        "object": "event",
        "type": "checkout.session.completed",
        "created": 1686089970,
        "data": {
            "object": {
                "id": "cs_123",
                "customer_details": {"email": "buyer@example.com"},
            }
        },
    }
    out = normalize_webhook(raw, event_id="ev1")
    assert set(out.keys()) == {"event_id", "source", "extracted", "raw"}
    assert out["source"] == "stripe"
    assert out["extracted"]["customer_id"] == "buyer@example.com"
    assert out["extracted"]["payer_email"] == "buyer@example.com"
    assert out["extracted"]["provider_event_id"] == "cs_123"


def test_normalize_webhook_stripe_setup_intent():
    """Stripe: setup_intent event with full payload, no amount."""
    raw = {
        "id": "evt_1NG8Du2eZvKYlo2CUI79vXWy",
        "object": "event",
        "type": "setup_intent.created",
        "created": 1686089970,
        "data": {
            "object": {
                "id": "seti_1NG8Du2eZvKYlo2C9XMqbR0x",
                "object": "setup_intent",
                "customer": None,
                "status": "requires_confirmation",
                "payment_method": "pm_1NG8Du2eZvKYlo2CYzzldNr7",
            }
        },
    }
    out = normalize_webhook(raw, event_id="ev_setup")
    assert set(out.keys()) == {"event_id", "source", "extracted", "raw"}
    assert out["source"] == "stripe"
    e = out["extracted"]
    assert e["provider_event_id"] == "seti_1NG8Du2eZvKYlo2C9XMqbR0x"
    assert e["event_type"] == "setup_intent.created"
    assert e["entity_type"] == "setup_intent"
    assert e["amount"] is None
    assert e["success"] is None


def test_normalize_webhook_stripe_customer_created():
    """Stripe: customer.created has description and idempotency_key in extracted."""
    raw = {
        "id": "evt_1T4GQELJ1PG5XUpnrlxWSUW3",
        "object": "event",
        "type": "customer.created",
        "created": 1771919566,
        "livemode": False,
        "data": {
            "object": {
                "id": "cus_U2L65zEspNR8L2",
                "object": "customer",
                "description": "(created by Stripe CLI)",
                "email": None,
                "metadata": {},
            }
        },
        "request": {
            "id": "req_a7RUVnKD62HDDD",
            "idempotency_key": "e0a925f5-a5b7-484b-af19-c7f18322b0f6",
        },
    }
    out = normalize_webhook(raw, event_id="ev_xyz")
    assert set(out.keys()) == {"event_id", "source", "extracted", "raw"}
    e = out["extracted"]
    assert e["provider_event_id"] == "cus_U2L65zEspNR8L2"
    assert e["event_type"] == "customer.created"
    assert e["entity_type"] == "customer"
    assert e["customer_id"] == "cus_U2L65zEspNR8L2"
    assert e["description"] == "(created by Stripe CLI)"
    assert e["metadata"] == {}
    assert e["idempotency_key"] == "e0a925f5-a5b7-484b-af19-c7f18322b0f6"
    assert e["livemode"] is False


def test_normalize_webhook_stripe_refund():
    """Stripe: refund event has refund_id, refund_amount, original_provider_id."""
    raw = {
        "object": "event",
        "type": "charge.refunded",
        "created": 1686089970,
        "data": {
            "object": {
                "id": "re_123",
                "object": "refund",
                "amount": 500,
                "currency": "usd",
                "charge": "ch_abc",
                "status": "succeeded",
            }
        },
    }
    out = normalize_webhook(raw, event_id="ev_refund")
    assert out["source"] == "stripe"
    e = out["extracted"]
    assert e["entity_type"] == "refund"
    assert e["refund_id"] == "re_123"
    assert e["refund_amount"] == {"value": 500, "currency": "USD"}
    assert e["original_provider_id"] == "ch_abc"


# --- Unknown fallback ---


def test_normalize_webhook_unknown_fallback():
    """Unknown payload returns minimal canonical output with source=unknown; only event_id, source, extracted, raw."""
    raw = {"some": "random", "payload": 123}
    out = normalize_webhook(raw, event_id="unk1")
    assert set(out.keys()) == {"event_id", "source", "extracted", "raw"}
    assert out["event_id"] == "unk1"
    assert out["source"] == "unknown"
    assert out["raw"] == raw
    e = out["extracted"]
    assert e["entity_type"] == "unknown"
    assert e["provider_event_id"] == ""
    assert e["customer_id"] == ""
    assert e["amount"] is None
    assert e["success"] is None
