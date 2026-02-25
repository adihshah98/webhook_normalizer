# Canonical webhook schema

Stored/API output has **only** these top-level keys:

- `event_id` (string) — our derived id
- `source` (string) — `stripe` | `adyen` | `paypal` | `unknown`
- `extracted` (object) — normalized fields per table below
- `raw` (object) — full inbound webhook body

Optional server-added fields (e.g. `recorded_at`) may appear at top level when added at write time.

## Extracted fields (inside `extracted`)

| Field | Type | Description |
|-------|------|-------------|
| `provider_event_id` | string | Provider's event/object id |
| `event_type` | string | Provider event type (e.g. `invoice.paid`, `charge.succeeded`, `AUTHORISATION`) |
| `entity_type` | string | High-level entity: `charge`, `refund`, `invoice`, `customer`, etc. |
| `canonical_event_type` | string | Cross-provider event: `payment.authorised`, `payment.captured`, `payment.refunded`, `payment.cancelled`, `payment.failed`, `invoice.paid`, `customer.created`, `dispute`, `other` |
| `canonical_payment_method` | string | Cross-provider method: `card`, `paypal`, `bank_transfer`, `other` |
| `occurred_at` | int \| string \| null | When the event happened (e.g. Unix timestamp) |
| `customer_id` | string | Provider customer id or email |
| `amount` | `{value, currency}` \| null | Amount in minor units; currency ISO |
| `success` | bool \| null | Outcome where known |
| `merchant_account` | string | Merchant/account id |
| `reference` | string | Your reference (e.g. order_id from metadata) |
| `livemode` | bool \| null | Live vs test |
| `payer_email` | string | Payer email (normalized) |
| `payment_method_type` | string | e.g. `card`, `paypal` |
| `description` | string | Human-readable description |
| `metadata` | object | Key-value from provider (e.g. Stripe `metadata`) |
| `idempotency_key` | string | Request idempotency key when present |
| `refund_id` | string | Refund/reversal id for refund events |
| `refund_amount` | `{value, currency}` \| null | Refund amount |
| `original_provider_id` | string | Original payment id (e.g. for refunds) |

All providers (Stripe, then Adyen, PayPal) map into this same `extracted` shape; missing values are empty string, null, or empty dict as appropriate.
