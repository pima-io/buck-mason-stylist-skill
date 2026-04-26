# ACP — fully agent-driven checkout via Pima

Pima exposes the **[Stripe + OpenAI Agentic Commerce Protocol](https://www.agenticcommerce.dev/)** (ACP, 2026-04-17 beta) at `/mcp/buckmason/acp/v1/checkouts/*`. This is the path for agents that want to handle the **entire** transaction — line items, shipping address, payment, confirmation — without bouncing the customer to a browser.

## When to use ACP vs. the regular cart endpoint

| Path | Use when |
|---|---|
| `POST /mcp/buckmason/cart` (Shopify permalink) | Default — customer reviews + pays in their browser. Zero PCI exposure. Apple Pay / Link / saved cards available. |
| `POST /mcp/buckmason/acp/v1/checkouts/*` (this) | Customer wants the agent to fully process the order — e.g., voice-driven concierge, BFCM speed runs, auto-replenishment, headless surfaces. Requires a Stripe **Shared Payment Token (SPT)** from the customer's device. |

**Don't pick ACP unless the customer has explicitly opted into agent-driven payment.** The default is the permalink — safer and simpler.

## Lifecycle (5 endpoints)

```
POST   /mcp/buckmason/acp/v1/checkouts                   → create
GET    /mcp/buckmason/acp/v1/checkouts/:id               → retrieve
PUT    /mcp/buckmason/acp/v1/checkouts/:id               → update line items / buyer / address
POST   /mcp/buckmason/acp/v1/checkouts/:id/complete      → submit payment
POST   /mcp/buckmason/acp/v1/checkouts/:id/cancel        → cancel
```

Every response carries the same envelope:

```json
{
  "id": "01HXY...",
  "protocol_version": "2026-04-17",
  "state": "created",                 // created | updated | completed | cancelled
  "currency": "usd",
  "line_items": [...],
  "buyer": {...},
  "fulfillment_address": {...},
  "fulfillment_options": [...],
  "selected_fulfillment_option_id": "ship_3",
  "payment_options": [...],
  "totals": { "subtotal_cents": 9800, "tax_cents": 0, "shipping_cents": 0, "total_cents": 9800, ... },
  "coupon": null,
  "pickup_location_id": null,
  "order_id": null,
  "payment_intent_id": null,
  "expires_at": "2026-04-26T19:33:08Z"
}
```

## End-to-end agent flow

```
1. Build cart                        → POST /checkouts
2. Customer confirms shipping        → PUT  /checkouts/:id (update buyer / fulfillment_address if needed)
3. Customer confirms total           → agent reads checkout.totals.total_cents back to user
4. Customer authorizes payment       → agent surfaces a Stripe Payment Element
                                       (Stripe.js / Apple Pay / Link) for the user to mint an SPT
5. Submit                            → POST /checkouts/:id/complete  (with confirmation header)
6. Confirm                           → echo order_id + payment_intent_id back to customer
```

## Step 1 — create a checkout

```http
POST /mcp/buckmason/acp/v1/checkouts
Content-Type: application/json
Idempotency-Key: <uuid>          ← strongly recommended; safe-retries the same checkout
```
```json
{
  "line_items": [
    { "sku": "OLIVE-DAILY-SHIRT-L", "quantity": 1 }
  ],
  "buyer": { "name": "Jane Doe", "email": "jane@example.com", "phone": "+15555550100" },
  "fulfillment_address": {
    "line1": "1320 Abbot Kinney Blvd", "city": "Venice", "state": "CA",
    "postal_code": "90291", "country": "US"
  },
  "pickup_location_slug": "abbot-kinney"   // optional
}
```

→ `201 Created` with the envelope above. `state: "created"`.

## Step 2 (optional) — update before submitting

Same envelope; PUT/PATCH any subset of `line_items`, `buyer`, `fulfillment_address`, `coupon`, `selected_fulfillment_option_id`. Totals + fulfillment_options recompute automatically when `line_items` change.

## Step 3 — explicit total confirmation

Before charging, the agent **must** echo the server-computed total to the customer in plain English ("That's $1,164 — including a $698 jacket. Confirm?") and only proceed on an unambiguous yes. The `acknowledged_total_cents` field on `/complete` is your safety net: Pima rejects the call if it doesn't match the server total exactly.

## Step 4 — mint the Shared Payment Token (SPT)

The customer enters card / Apple Pay / Link in **the agent's** Stripe Payment Element. Stripe returns an SPT (string starting `spt_`) scoped to:
- This Pima merchant
- This currency
- This maximum amount
- A short expiry (~10 minutes)

The agent never sees a PAN. SPT generation is a Stripe.js client-side operation — the skill's job is to surface that flow to the customer (in ChatGPT this happens automatically inside the conversation; in a custom agent you'll embed Stripe.js).

## Step 5 — complete

```http
POST /mcp/buckmason/acp/v1/checkouts/:id/complete
Content-Type: application/json
X-Customer-Confirmation: yes-charge-it      ← MUST be present and exactly this value
```
```json
{
  "payment_data": { "type": "shared_payment_token", "token": "spt_..." },
  "acknowledged_total_cents": 9800
}
```

→ `200 OK`, `state: "completed"`, with `order_id` and `payment_intent_id` populated.

### Hard guarantees enforced by Pima

| Guard | Behaviour on failure |
|---|---|
| Missing `X-Customer-Confirmation: yes-charge-it` header | `403 confirmation_required` |
| `acknowledged_total_cents` ≠ server total | `422 total_mismatch` (with `server_total_cents` in error payload) |
| Missing `payment_data.token` | `422 payment_data_required` |
| Checkout already terminal | `409 checkout_terminal` |
| Checkout expired (default 60 min) | `410 checkout_expired` |
| Card declined / Stripe error | `402` with `code: card_declined` or `stripe_error` |
| Company has no Stripe creds | `402 stripe_not_configured` |

### Idempotency

Pass an `Idempotency-Key` header on `POST /checkouts` and `POST /complete`. Re-sending the same key within the checkout's lifetime returns the same response — never double-charges. Use a UUID per checkout-attempt; rotate on user retries.

## Step 6 — cancel (any time before completion)

```http
POST /mcp/buckmason/acp/v1/checkouts/:id/cancel
{ "reason": "changed_mind" }
```

## Pickup + ACP

If `pickup_location_slug` (or `pickup_location_id`) was set on `/checkouts`, the response's `fulfillment_options[]` includes a `pickup_<id>` option with `all_items_in_stock` and any `shortages[]`. The agent should:

1. Surface "Pickup at <store> in ~2 hours, or ship for $X arriving in N days" to the customer.
2. PUT `selected_fulfillment_option_id: "pickup_<id>"` (or `ship_<id>`) before completing.
3. If `all_items_in_stock: false`, fall back to ship or split — never silently substitute sizes.

## Worked example — full transcript

```text
[Agent → POST /mcp/buckmason/acp/v1/checkouts]
  Idempotency-Key: 7c89e24b-2…
  body: { line_items: [{ sku: "OLIVE-DAILY-SHIRT-L", quantity: 1 }], buyer: {…}, fulfillment_address: {…} }
[Pima → 201]
  { id: "01HXY...", state: "created", totals: { total_cents: 9800 } }

[Agent → user] "Olive Daily Shirt, size L, shipping to 1320 Abbot Kinney. Total $98. Confirm?"
[User → agent] "Yes, charge it"

[Agent → user] *Stripe Payment Element appears, user completes Apple Pay*
[Stripe → agent SDK] spt_test_xyz

[Agent → POST /mcp/buckmason/acp/v1/checkouts/01HXY…/complete]
  X-Customer-Confirmation: yes-charge-it
  body: { payment_data: { type: "shared_payment_token", token: "spt_test_xyz" },
          acknowledged_total_cents: 9800 }
[Pima → 200]
  { state: "completed", order_id: 9876, payment_intent_id: "pi_..." }

[Agent → user] "Done — order #9876. Confirmation email coming to jane@example.com."
```

## Checkout safety — required prompt rules for any agent loading this skill

- **Always read the total back to the user before completing.** Verbatim ("$98.00") and including currency.
- **Require an unambiguous "yes/charge it" in the same turn as the read-back.** "OK" alone is not consent.
- **Never call `/complete` from a chained tool-use without a fresh user message.** Confirmation must be explicit per checkout.
- **On any 4xx error from `/complete`, do NOT auto-retry.** Surface the error to the user. They decide what to do.
- **On a `total_mismatch` 422, re-read the corrected total before re-attempting.** This catches hallucinated prices.
- **Always disclose**: "Your card will be charged $X.XX through Stripe via Buck Mason."

## Discovery

`GET /mcp/buckmason/manifest` advertises the ACP surface in its `acp` block:

```json
{
  "acp": {
    "protocol_version": "2026-04-17",
    "base_url": "/mcp/buckmason/acp/v1"
  },
  "endpoints": [
    { "method": "POST", "path": "/mcp/<slug>/acp/v1/checkouts", ... },
    ...
  ]
}
```

Agents that don't recognize ACP should fall back to `POST /mcp/buckmason/cart` (Shopify permalink). ACP is purely additive.
