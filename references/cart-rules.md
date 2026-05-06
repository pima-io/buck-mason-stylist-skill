# Cart-affordance rules — Path A (Shopify cart-link)

Detailed behavior for `POST /mcp/buckmason/cart`. The headline rule is in `SKILL.md` workflow #4; this doc covers the pickup edge cases, the coupon/credit handling for logged-in customers, and the rule against silent substitutions.

## In-store pickup variant

When the customer says "pickup," "I'll grab it," "have it ready at [store]," or names a Buck Mason store, attach a pickup hint to the cart body:

```json
{ "items": [...],
  "pickup_location_slug": "abbot-kinney"  // or pickup_location_id: 2
}
```

The MCP attaches `?attributes[Pickup-Location]=<name>` to the returned `checkout_url` so the Shopify checkout pre-selects pickup at that store.

### Pre-build stock check

**Before building** any pickup cart, the agent confirms every SKU is in stock at the named store via `/mcp/buckmason/stock/:sku?near_zip=…` (filter by SKU + location). Behavior by stock state:

| Customer-named store stock state | Action |
|---|---|
| All items in stock | Build pickup cart, return `checkout_url` + a one-line "Ready for pickup at \<store\>" confirmation |
| Some out at the chosen store | Don't auto-split. Tell the customer the gap and ask: pickup the in-stock items + ship the rest as two carts, OR ship the whole order as one |
| Customer didn't name a store ("for pickup near me") | Pick the nearest `pickup_enabled` store with **all** SKUs in stock. If none qualifies, fall back to ship-it with a one-line "no nearby store has all of these in stock; shipping default" |
| Customer named a store but it's out for the SKU set | Suggest the nearest in-stock pickup-enabled store and confirm before building |
| Pickup-disabled location | Silently skip, pick the next-nearest pickup-enabled store |

### Don't substitute sizes for pickup convenience

If the customer's exact size is out at the chosen store but a different size is in, surface and ask — **never substitute silently**. A wrong-size garment at home is a return + restocking penalty, not a convenience win.

## Logged-in coupon / credit (Pima-side cart)

When the customer is logged in (`profile.md → jwt` is present) and wants to apply a coupon or store credit *before* they land on Shopify checkout (e.g., to see the discounted total in the cart preview), use the Pima-side cart:

1. `POST /api/update_cart` — push items to the persisted cart on Pima
2. `POST /api/add_coupon_or_customer_credit` — apply the code
3. Surface the resulting `checkout_url` from the response

This path requires a JWT (workflow #5 path 1a). Without a JWT, the cart-link path applies the coupon as a `?discount=<code>` query param on the Shopify URL — Shopify validates it at checkout, but the customer doesn't see the discounted total until they're on Shopify's page.

## What `/cart` will and won't accept

Verified against `pima-master/app/controllers/mcp_controller.rb#cart` (2026-05-09):

- Line items take `slug_or_code` (or aliases `slug` / `code`) — **lowercase product slug** that resolves to a product, plus a separate `size` field. Shape diverges from `/checkout` (MPP) which takes `sku` directly. See `references/mcp-api.md` for the divergence.
- `coupon` is passed through to the Shopify URL as `?discount=`. Strict validation happens at Shopify's checkout step, not at `/cart`.
- `pickup_location_slug` (parameterize'd against `Location#short_name` or `Location#name`) and `pickup_location_id` are both accepted; `name` doesn't exist at this endpoint (only at the per-line-item level on `/checkout`).
- `allow_pickup_partial: true` opts into building a pickup cart even when some SKUs are short at the store. Off by default.
- The endpoint is fully stateless — no JWT, no cookie, no session. The returned `checkout_url` is the only artifact; nothing persists server-side until the customer completes Shopify checkout.

## Errors the agent may hit

| Status | Body | Meaning |
|---|---|---|
| 422 | `{ "error": "items required" }` | Empty items array |
| 422 | `{ "error": "no items resolved", "items": [...] }` | Every item failed slug/size resolution — typo or stale slug. Agent should re-resolve via `/products?q=…` |
| 422 | `{ "error": "one or more SKUs are not synced to Shopify", "skus": [...] }` | Buck Mason has the SKU in Pima but not yet pushed to Shopify (rare during a product launch). Drop the offending pieces or wait + retry |
| 422 | `{ "error": "items not in stock for pickup at <store>", "shortages": [...] }` | Pre-build pickup stock check failed. Surface the shortages, fall back per the table above |

## Composition with other workflows

- The `html-cart` lookbook (workflow #3) writes its handoff in plain prose; the agent extracts items + sizes from the prose and feeds Path A or Path B from there.
- Workflow #5 (order tracking + returns) starts after Path A or Path B succeeds — the customer asks "where's my order?" with the `order_code` from the receipt.
