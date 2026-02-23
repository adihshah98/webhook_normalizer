import hashlib
import json


def canonical_json(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def derive_event_id(payload: dict, idempotency_key: str | None) -> str:
    if idempotency_key:
        return idempotency_key[:64]
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()
