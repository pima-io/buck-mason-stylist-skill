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
  "totals": {
    "subtotal_cents": 9800, "discount_cents": 0, "shipping_cents": 0,
    "tax_cents": 0, "credit_applied_cents": 0,
    "total_cents": 9800,            // gross order value
    "charge_cents": 9800,           // amount that hits Stripe (total − credit)
    "subtotal": "$98.00", "discount": "$0.00", "shipping": "$0.00",
    "tax": "$0.00", "credit_applied": "$0.00",
    "total": "$98.00", "charge": "$98.00"
  },
  "coupon": null,
  "coupon_status": {},
  "customer_credit_codes": [],
  "credit_status": [],
  "credit_applied_cents": 0,
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

Same envelope; PUT/PATCH any subset of `line_items`, `buyer`, `fulfillment_address`, `coupon`, `customer_credit_codes`, `selected_fulfillment_option_id`. Totals (including coupon discount + credit application) recompute automatically when any pricing input changes.

### Coupons + customer credits — bearer codes (no auth)

Both follow the same model as Buck Mason POS: anyone with the code can apply it (same security posture as a Starbucks gift card).

```http
POST /mcp/buckmason/acp/v1/checkouts
{
  "line_items": [...],
  "buyer": {...},
  "fulfillment_address": {...},
  "coupon": "SPRING25",                        // single string — Pima Coupon
  "customer_credit_codes": ["GC-12345"]        // array — Pima CustomerCredit (gift cards, store credit)
}
```

**Coupon results** land in `coupon_status`:
```json
"coupon_status": { "code": "SPRING25", "applied": true, "amount_cents": 1000, "type": "percent" }
// or, soft-warn on failure:
"coupon_status": { "code": "BAD", "applied": false, "error": "coupon_not_found" }
```

**Credit results** land in `credit_status` — one entry per code, applied in order until the order is paid:
```json
"credit_status": [
  { "code": "GC-12345", "applied": true, "amount_cents": 5000, "balance_remaining_cents": 0 },
  { "code": "GC-67890", "applied": true, "amount_cents": 3000, "balance_remaining_cents": 1500 }
]
```

**Failure modes per code** (each is a soft-warn — the checkout still creates):
- `coupon_not_found` — unknown coupon
- `coupon` `not_applicable` — exists but doesn't apply (cart total / category / customer rules)
- `credit_not_found` — unknown credit code
- `credit_disabled` — credit explicitly disabled
- `credit_no_balance` — credit exhausted
- `order_already_paid` — earlier credits in the array already covered the total

**On `complete`**: Stripe is charged for `totals.charge_cents` (which is `total_cents − credit_applied_cents`). If credit covers the full order (`charge_cents == 0`), the SPT step is skipped entirely — `payment_data` becomes optional and Stripe is not called.

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
```
```json
{
  "payment_data": { "type": "shared_payment_token", "token": "spt_..." },
  "acknowledged_total_cents": 9800
}
```

→ `200 OK`, `state: "completed"`, with `order_id` and `payment_intent_id` populated. The customer's consent is the SPT itself (Stripe-issued, scoped, time-limited) — there is no additional Pima-side confirmation header. The `acknowledged_total_cents` echo is the agent-side guard against hallucinated totals.

If `totals.charge_cents == 0` (i.e., customer credit covered the full order), `payment_data` may be omitted entirely and Stripe is not called — `payment_intent_id` will be `null` in the completed checkout.

### Hard guarantees enforced by Pima

| Guard | Behaviour on failure |
|---|---|
| `acknowledged_total_cents` ≠ server `total_cents` | `422 total_mismatch` (with `server_total_cents` in error payload) |
| Missing `payment_data.token` when `charge_cents > 0` | `422 payment_data_required` |
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
  body: { payment_data: { type: "shared_payment_token", token: "spt_test_xyz" },
          acknowledged_total_cents: 9800 }
[Pima → 200]
  { state: "completed", order_id: 9876, payment_intent_id: "pi_..." }

[Agent → user] "Done — order #9876. Confirmation email coming to jane@example.com."
```

## Checkout safety — required prompt rules for any agent loading this skill

The Stripe Shared Payment Token IS the user's consent (Stripe-issued, scoped, time-limited). The agent's responsibility is to make sure the user knows what they're authorizing before the SPT is minted, and to never silently retry on failure.

- **Always read the total back to the user before requesting an SPT.** Verbatim ("$98.00 — $5.00 of that paid by gift card GC-12345; Stripe will charge $93.00") and including currency.
- **Require an unambiguous "yes" in the same turn as the read-back, before showing the Stripe Payment Element.** "OK" alone is not consent.
- **Never call `/complete` from a chained tool-use without a fresh user message.** Re-confirm each checkout.
- **On any 4xx error from `/complete`, do NOT auto-retry.** Surface the error to the user. They decide what to do.
- **On a `total_mismatch` 422, re-read the corrected total before re-attempting.** This catches hallucinated prices.
- **When announcing coupon/credit application, name the code and the saving.** "Applied SPRING25 (-$10) and gift card GC-12345 ($25 of $50 used)" — never silently apply.
- **Always disclose** the payment processor: "Your card will be charged $X.XX through Stripe via Buck Mason."

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
