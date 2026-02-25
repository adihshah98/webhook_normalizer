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
    assert e["canonical_event_type"] == "invoice.paid"
    assert e["canonical_payment_method"] == "other"


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
    assert e["canonical_event_type"] == "customer.created"


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
    assert e["canonical_event_type"] == "payment.refunded"


# --- Adyen ---


def test_normalize_webhook_adyen():
    """Adyen: output has event_id, source=adyen, extracted with AUTHORISATION fields."""
    raw = {
        "live": "false",
        "notificationItems": [
            {
                "NotificationRequestItem": {
                    "pspReference": "7914073381342284",
                    "eventCode": "AUTHORISATION",
                    "eventDate": "2019-05-06T17:15:34.121+02:00",
                    "success": "true",
                    "merchantAccountCode": "TestMerchant",
                    "merchantReference": "Order-123",
                    "amount": {"value": 1130, "currency": "EUR"},
                    "paymentMethod": "visa",
                    "additionalData": {"shopperEmail": "shopper@example.com", "shopperReference": "shopper-1"},
                }
            }
        ],
    }
    out = normalize_webhook(raw, event_id="ev_adyen")
    assert set(out.keys()) == {"event_id", "source", "extracted", "raw"}
    assert out["event_id"] == "ev_adyen"
    assert out["source"] == "adyen"
    assert out["raw"] == raw
    e = out["extracted"]
    assert e["provider_event_id"] == "7914073381342284"
    assert e["event_type"] == "AUTHORISATION"
    assert e["entity_type"] == "payment"
    assert e["occurred_at"] == "2019-05-06T17:15:34.121+02:00"
    assert e["amount"] == {"value": 1130, "currency": "EUR"}
    assert e["success"] is True
    assert e["merchant_account"] == "TestMerchant"
    assert e["reference"] == "Order-123"
    assert e["livemode"] is False
    assert e["payer_email"] == "shopper@example.com"
    assert e["customer_id"] == "shopper-1"
    assert e["payment_method_type"] == "visa"
    assert e["canonical_event_type"] == "payment.authorised"
    assert e["canonical_payment_method"] == "card"


def test_normalize_webhook_adyen_refund():
    """Adyen: REFUND event has refund_id, refund_amount, original_provider_id."""
    raw = {
        "live": "true",
        "notificationItems": [
            {
                "NotificationRequestItem": {
                    "pspReference": "ref_9914073381342284",
                    "originalReference": "7914073381342284",
                    "eventCode": "REFUND",
                    "eventDate": "2019-05-07T10:00:00+02:00",
                    "success": "true",
                    "merchantAccountCode": "TestMerchant",
                    "merchantReference": "Order-123-refund",
                    "amount": {"value": 500, "currency": "EUR"},
                    "paymentMethod": "visa",
                }
            }
        ],
    }
    out = normalize_webhook(raw, event_id="ev_adyen_refund")
    assert out["source"] == "adyen"
    e = out["extracted"]
    assert e["entity_type"] == "refund"
    assert e["refund_id"] == "ref_9914073381342284"
    assert e["refund_amount"] == {"value": 500, "currency": "EUR"}
    assert e["original_provider_id"] == "7914073381342284"
    assert e["livemode"] is True
    assert e["canonical_event_type"] == "payment.refunded"
    assert e["canonical_payment_method"] == "card"


def test_normalize_webhook_canonical_cross_provider():
    """Stripe charge.succeeded and Adyen CAPTURE both map to payment.captured."""
    stripe_raw = {
        "object": "event",
        "type": "charge.succeeded",
        "created": 1686089970,
        "data": {
            "object": {
                "id": "ch_123",
                "amount": 2500,
                "currency": "usd",
                "status": "succeeded",
            }
        },
    }
    adyen_raw = {
        "live": "false",
        "notificationItems": [
            {
                "NotificationRequestItem": {
                    "pspReference": "8815073381342284",
                    "eventCode": "CAPTURE",
                    "eventDate": "2019-06-28T18:03:50+01:00",
                    "success": "true",
                    "merchantAccountCode": "TestMerchant",
                    "merchantReference": "order-1",
                    "amount": {"value": 2500, "currency": "USD"},
                    "paymentMethod": "visa",
                }
            }
        ],
    }
    stripe_out = normalize_webhook(stripe_raw, event_id="e1")
    adyen_out = normalize_webhook(adyen_raw, event_id="e2")
    assert stripe_out["extracted"]["canonical_event_type"] == "payment.captured"
    assert adyen_out["extracted"]["canonical_event_type"] == "payment.captured"
    assert stripe_out["extracted"]["canonical_payment_method"] == "other"  # no payment_method_details
    assert adyen_out["extracted"]["canonical_payment_method"] == "card"


# --- PayPal ---


def test_normalize_webhook_paypal():
    """PayPal: output has event_id, source=paypal, extracted with PAYMENT.CAPTURE.COMPLETED fields."""
    raw = {
        "id": "WH-3F562076HD293871E-75F399086E414290U",
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "create_time": "2024-05-16T05:19:19.355Z",
        "resource_type": "capture",
        "summary": "Payment completed for $ 500.0 USD",
        "resource": {
            "id": "3Y662965014333303",
            "status": "COMPLETED",
            "amount": {"value": "500.00", "currency_code": "USD"},
            "payee": {"merchant_id": "QDGTZ7B92B9QT", "email_address": "[email protected]"},
            "supplementary_data": {"related_ids": {"order_id": "9P99943869582473S"}},
        },
    }
    out = normalize_webhook(raw, event_id="ev_paypal")
    assert set(out.keys()) == {"event_id", "source", "extracted", "raw"}
    assert out["event_id"] == "ev_paypal"
    assert out["source"] == "paypal"
    e = out["extracted"]
    assert e["provider_event_id"] == "WH-3F562076HD293871E-75F399086E414290U"
    assert e["event_type"] == "PAYMENT.CAPTURE.COMPLETED"
    assert e["entity_type"] == "payment"
    assert e["canonical_event_type"] == "payment.captured"
    assert e["canonical_payment_method"] == "paypal"
    assert e["amount"]["value"] == 50000
    assert e["amount"]["currency"] == "USD"
    assert e["success"] is True
    assert e["merchant_account"] == "QDGTZ7B92B9QT"
    assert e["reference"] == "9P99943869582473S"


def test_normalize_webhook_paypal_refund():
    """PayPal: PAYMENT.CAPTURE.REFUNDED has refund_id, refund_amount, original_provider_id."""
    raw = {
        "id": "WH-refund-123",
        "event_type": "PAYMENT.CAPTURE.REFUNDED",
        "create_time": "2024-05-16T06:00:00Z",
        "resource_type": "refund",
        "resource": {
            "id": "refund-456",
            "status": "COMPLETED",
            "amount": {"value": "25.00", "currency_code": "USD"},
            "parent_payment": "3Y662965014333303",
        },
    }
    out = normalize_webhook(raw, event_id="ev_paypal_refund")
    assert out["source"] == "paypal"
    e = out["extracted"]
    assert e["entity_type"] == "refund"
    assert e["canonical_event_type"] == "payment.refunded"
    assert e["refund_id"] == "refund-456"
    assert e["refund_amount"]["value"] == 2500
    assert e["original_provider_id"] == "3Y662965014333303"


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
    assert e["canonical_event_type"] == "other"
    assert e["canonical_payment_method"] == "other"
    assert e["provider_event_id"] == ""
    assert e["customer_id"] == ""
    assert e["amount"] is None
    assert e["success"] is None
