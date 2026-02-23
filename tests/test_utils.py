import pytest

from app.utils.event_id import canonical_json, derive_event_id
from app.utils.normalize import normalize_webhook


def test_canonical_json():
    assert canonical_json({"a": 1, "b": 2}) == '{"a":1,"b":2}'


def test_normalize_webhook_crm():
    raw = {
        "event_type": "contact.created",
        "event_id": "00X8a00000123Ab",
        "occurred_at": "2024-01-01T12:34:56Z",
        "account": {"id": "acct_789", "name": "Acme Corp"},
        "contact": {
            "id": "0038a00000456Cd",
            "email": "alice@acme.com",
            "first_name": "Alice",
            "last_name": "Smith",
        },
    }
    out = normalize_webhook(raw, event_id="abc123")
    assert out["event_id"] == "abc123"
    assert out["source"] == "crm"
    assert out["customer_id"] == "acct_789"
    assert out["event_type"] == "contact.created"
    assert out["entity_type"] == "contact"
    assert out["entity_id"] == "0038a00000456Cd"
    assert out["payload"] == {
        "email": "alice@acme.com",
        "first_name": "Alice",
        "last_name": "Smith",
    }
    assert out["raw"] == raw


def test_normalize_webhook_billing():
    raw = {
        "type": "customer.subscription.created",
        "created": 1640995200,
        "customer_id": "cus_abc",
        "data": {"object": {"id": "sub_123", "plan": "pro", "quantity": 5}},
    }
    out = normalize_webhook(raw, event_id="ev_xyz")
    assert out["event_id"] == "ev_xyz"
    assert out["source"] == "billing"
    assert out["customer_id"] == "cus_abc"
    assert out["event_type"] == "customer.subscription.created"
    assert out["entity_type"] == "customer"
    assert out["entity_id"] == "sub_123"
    assert out["payload"] == {"plan": "pro", "quantity": 5}
    assert out["raw"] == raw


def test_normalize_webhook_auto_detect_billing():
    raw = {"type": "invoice.paid", "data": {"object": {"id": "in_1", "amount": 1000}}}
    out = normalize_webhook(raw, event_id="ev1")
    assert out["source"] == "billing"
    assert out["entity_id"] == "in_1"
