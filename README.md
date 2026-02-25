# webhook-adapter

Ingest payment webhooks (Stripe, Adyen, and later PayPal), normalize to a common schema, and persist.

## Canonical webhook schema

Stored and API output use only: `event_id`, `source`, `extracted`, `raw`. All normalized fields live in `extracted`. See [docs/SCHEMA.md](docs/SCHEMA.md) for the full canonical field list and types.
