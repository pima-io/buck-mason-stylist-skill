# MPP — fully agent-driven checkout via Pima (HTTP 402 challenge)

Pima exposes the **[Merchant Payments Protocol](https://mpp.dev)** at `POST https://pima.io/mcp/buckmason/checkout`. This is the path for agents that want to handle the **entire** transaction — line items, shipping address, payment, confirmation — without bouncing the customer to a browser.

The agent-side tooling is **[stripe/link-cli](https://github.com/stripe/link-cli)** — a Node CLI / MCP server that lets an AI agent fetch a one-time **Stripe Shared Payment Token (SPT)** from the customer's Link wallet (push-approved on the customer's phone). That SPT is what the agent submits to Pima's `/checkout` endpoint to clear the HTTP 402 challenge.

## When to use MPP vs. the regular cart endpoint

| Path | Use when |
|---|---|
| `POST /mcp/buckmason/cart` (Shopify permalink) | Default — customer reviews + pays in their browser. Zero PCI exposure for the agent. Apple Pay / Link / saved cards available. |
| `POST /mcp/buckmason/checkout` (this — MPP) | Customer wants the agent to fully process the order — voice-driven concierge, BFCM speed runs, auto-replenishment, headless surfaces. Requires an agent that can mint a Stripe SPT (typically via `link-cli` against the customer's Link wallet). |

**Don't pick MPP unless the customer has explicitly opted into agent-driven payment.** The default is the permalink — safer and simpler. The customer's Link push-approval IS the consent step that replaces the browser redirect.

## Lifecycle (one endpoint, two phases)

```
POST /mcp/buckmason/checkout                       — phase 1 (challenge)
POST /mcp/buckmason/checkout                       — phase 2 (charge)
   with Authorization: Payment <SPT>
```

Both POSTs carry the same body. The server is **stateless** — it doesn't store a checkout between the two calls; the agent re-sends the cart the second time.

### Phase 1 — challenge

```http
POST /mcp/buckmason/checkout
Content-Type: application/json
Idempotency-Key: <uuid>          ← optional but recommended; forwarded to Stripe in phase 2
```
```json
{
  "line_items": [{ "sku": "OLIVE-DAILY-SHIRT-L", "quantity": 1 }],
  "buyer": { "name": "Jane Doe", "email": "jane@example.com", "phone": "+15555550100" },
  "fulfillment_address": { "line1": "1320 Abbot Kinney Blvd", "city": "Venice",
                           "state": "CA", "postal_code": "90291", "country": "US" },
  "pickup_location_slug": "abbot-kinney",   // optional
  "coupon": "SPRING25",                     // optional, bearer code
  "customer_credit_codes": ["GC-12345"]     // optional, bearer codes
}
```

Server response:

```http
HTTP/1.1 402 Payment Required
WWW-Authenticate: Payment realm="pima", scheme="shared_payment_token", amount=9800, currency="usd"
Cache-Control: no-store
```
```json
{
  "payment_required": true,
  "currency": "usd",
  "line_items": [...],
  "buyer": {...},
  "fulfillment_address": {...},
  "pickup_location_id": 2,
  "pickup_location_name": "Abbot Kinney Mens",
  "coupon": "SPRING25",
  "coupon_status": { "code": "SPRING25", "applied": true, "amount_cents": 1000, "type": "fixed" },
  "customer_credit_codes": ["GC-12345"],
  "credit_status": [
    { "code": "GC-12345", "applied": true, "amount_cents": 5000, "balance_remaining_cents": 0 }
  ],
  "credit_applied_cents": 5000,
  "totals": {
    "subtotal_cents": 9800, "discount_cents": 1000, "shipping_cents": 0,
    "tax_cents": 0, "credit_applied_cents": 5000,
    "total_cents": 8800,                  // gross order value
    "charge_cents": 3800,                 // amount Stripe will charge after credit
    "subtotal": "$98.00", "discount": "$10.00", "shipping": "$0.00",
    "tax": "$0.00", "credit_applied": "$50.00",
    "total": "$88.00", "charge": "$38.00"
  },
  "payment_options": [
    { "type": "shared_payment_token", "provider": "stripe", "protocol": "mpp_v1",
      "protocol_homepage": "https://mpp.dev",
      "amount_cents": 3800, "currency": "usd" }
  ]
}
```

### Phase 2 — read total back, mint SPT, retry with Authorization

1. Agent reads the `total` (and the breakdown — coupon, credit, shipping, tax) back to the customer **verbatim**.
2. Customer says yes.
3. Agent runs `link-cli spend-request create --amount 3800 --currency usd --merchant pima` (or the MCP-server equivalent). Customer push-approves on their phone in the Link app. Stripe returns an SPT.
4. Agent re-POSTs the same cart with the SPT and the `acknowledged_total_cents` echo:

```http
POST /mcp/buckmason/checkout
Content-Type: application/json
Authorization: Payment <SPT>             ← canonical MPP form (Bearer also accepted)
Idempotency-Key: <uuid>                  ← reuse the same key from phase 1
```
```json
{
  "line_items": [...],            // identical to phase 1
  "buyer": {...},
  "fulfillment_address": {...},
  "pickup_location_slug": "abbot-kinney",
  "coupon": "SPRING25",
  "customer_credit_codes": ["GC-12345"],
  "acknowledged_total_cents": 8800   ← matches totals.total_cents from phase 1
}
```

Server response on success:

```http
HTTP/1.1 200 OK
Payment-Receipt: pi_3OabcXYZ...
Cache-Control: no-store
```
```json
{
  // ...same cart envelope as phase 1 plus:
  "state": "completed",
  "order_id": 9876,
  "order_code": "BM-9876",
  "payment_intent_id": "pi_3OabcXYZ..."
}
```

### Hard guarantees enforced by Pima

| Guard | Behaviour on failure |
|---|---|
| `acknowledged_total_cents` ≠ server `total_cents` | `422 total_mismatch` (with `server_total_cents` in the error payload) |
| Authorization header absent | `402 Payment Required` (challenge re-issued — agent should mint SPT and retry) |
| Card declined / Stripe error | `402` with `code: card_declined` or `stripe_error` |
| Company has no Stripe creds | `402 stripe_not_configured` |
| Bad pickup slug / pickup-disabled location | `404 pickup_location_not_found` / `422 pickup_disabled` |

`Authorization` accepts both the canonical `Payment <SPT>` form (per MPP) and `Bearer <SPT>` as a fallback for clients that only know the OAuth-style header.

### When credit covers the full order

If `customer_credit_codes` covers the entire `total_cents` (so `charge_cents == 0`), the SPT step is skipped:
- Phase 1 returns the same 402 challenge with `payment_options[].amount_cents: 0`
- Phase 2 still requires an `Authorization` header (any value) so the agent has explicitly opted into the success branch — but the SPT is unused and Stripe is not called
- Response includes `payment_intent_id: null`

### Coupons + customer credits — bearer codes (no auth)

Both follow the same model as Buck Mason POS — anyone with the code can apply (gift-card semantics).

```json
"coupon": "SPRING25",                     // single string — Pima Coupon
"customer_credit_codes": ["GC-12345"]     // array — Pima CustomerCredit (gift cards, store credit)
```

Failures are **soft-warns** (the checkout still produces a challenge):
- `coupon_not_found` / `not_applicable` / `coupon_disabled`
- `credit_not_found` / `credit_disabled` / `credit_no_balance` / `order_already_paid`

The agent should surface ("Your coupon expired — continue without it?") rather than abort.

## Discovery

`GET /mcp/buckmason/manifest` advertises the MPP surface in its `mpp` block:

```json
{
  "mpp": {
    "spec": "https://mpp.dev",
    "base_url": "/mcp/buckmason/checkout",
    "agent_tools": ["https://github.com/stripe/link-cli"]
  },
  "endpoints": [
    { "method": "POST", "path": "/mcp/<slug>/checkout", ... }
  ]
}
```

Agents that don't recognize MPP should fall back to `POST /mcp/buckmason/cart` (Shopify permalink). MPP is purely additive.

## Sandbox / staging

Two affordances let an agent run against staging or soak-test against prod without moving real money:

### `Pima-Environment` response header (and manifest field)
Every MCP/MPP response stamps `Pima-Environment: <production|sandbox>`. The same value is in `manifest.environment`. Production is the default; on `staging.pima.io` the header reads `sandbox`. Use this to refuse to charge real money when the agent thinks it's hitting prod but the response says sandbox (or vice versa).

```bash
curl -sI https://staging.pima.io/mcp/buckmason/manifest | grep -i pima-environment
# Pima-Environment: sandbox
```

### `?dry_run=true` query param on `/checkout`
Skips Stripe entirely. Returns a fake `Payment-Receipt: pi_dry_run_<random>` header, sets `state: "dry_run"` in the body, sets `Pima-Dry-Run: true` response header, and does **not** materialize a Pima Order. Lets agents validate the full envelope shape (cart resolution, totals, coupon/credit application, total-mismatch guards, Authorization parsing) without authorizing a payment.

```bash
curl -sS -i -X POST 'https://staging.pima.io/mcp/buckmason/checkout?dry_run=true' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Payment any-string-works-in-dry-run' \
  -d '{"line_items":[{"sku":"<sku>","quantity":1}],
        "buyer":{...}, "fulfillment_address":{...},
        "acknowledged_total_cents": 9800}'
# → 200 OK
# Payment-Receipt: pi_dry_run_a1b2c3d4
# Pima-Dry-Run: true
```

Use `dry_run` for: agent regression tests against prod (without billing customers), end-to-end demos in front of stakeholders, smoke tests after a deploy, and validating a customer's chosen pickup location + size availability before requesting their actual SPT.

## Checkout safety — required prompt rules

The Stripe Shared Payment Token IS the customer's consent (Stripe-issued, scoped, time-limited; minted only after the customer push-approves in the Link app). The agent's responsibility is to make sure the customer knows what they're authorizing **before** the SPT is requested, and to never silently retry on failure.

- **Always read the total back to the customer before requesting the SPT.** Verbatim ("$88.00 — $5.00 paid by gift card GC-12345; Stripe will charge $38.00 to your card") and including currency.
- **Require an unambiguous "yes" in the same turn before kicking off `link-cli spend-request create`.** "OK" alone is not consent.
- **Never re-POST `/checkout` from a chained tool-use without a fresh user message between the read-back and the SPT mint.** Re-confirm each charge.
- **On any 4xx error, do NOT auto-retry.** Surface the error to the customer; they decide what to do.
- **On a `total_mismatch` 422, re-read the corrected total before re-attempting.** This catches hallucinated prices.
- **When announcing coupon/credit application, name the code and the saving.** "Applied SPRING25 (-$10) and gift card GC-12345 ($50 of $50 used)" — never silently apply.
- **Always disclose** the payment processor: "Your card will be charged $X.XX through Stripe via Buck Mason."
