# Pima API reference (customer-facing endpoints)

> For shopping flows, **start with `references/mcp-api.md`** (the `/mcp/*` endpoints). They give you rich product data, per-store stock, and one-call cart links without any of the auth/session juggling below. Use this `/api/*` reference only for: customer login, account/order history (wardrobe seeding), restock notifications, and card-on-file checkout.

Base URL for Buck Mason: `https://www.buckmason.com` (the Pima app serves `/api/*` from the same host as the storefront).

All endpoints return JSON unless noted. Successful responses are 200 OK; errors return `{ "error": "…" }` or `{ "errors": { … } }`.

## Auth

Three modes coexist:

| Mode | How | Used by |
|---|---|---|
| **Guest** (no auth) | Just call the endpoint | Catalog, locations, cart, public product data |
| **Customer JWT** | `Authorization: Bearer <jwt>` header (or `?token=<jwt>` query param on some endpoints) | Account, orders, order history, returns |
| **Inventory API key** | `?token=<inventory_api_key>` query param | `GET /api/inventory`, `GET /api/customers` (CSV streaming, partner-only) |

The JWT comes from `POST /api/login` or `POST /api/register`. Persist it for the session and resend on every authenticated call.

## Catalog

### `GET /api/ping`
Health/identity. Returns the company name as plain text. Use to verify base URL.

### `GET /api/product_structure`
Taxonomy. No auth. Cache for the session.

```json
{
  "product_types": [{ "id": 1, "name": "Apparel" }],
  "categories":    [{ "id": 1, "name": "Tops", "product_type_id": 1, "product_type_name": "Apparel" }],
  "styles":        [{ "id": 1, "name": "T-Shirt", "category_id": 1, "category_name": "Tops" }],
  "product_lines": [{ "id": 1, "name": "Basic Crew", "style_id": 1, "gender": "u",
                      "category_name": "Tops", "style_name": "T-Shirt" }],
  "colors":        [{ "id": 1, "name": "Navy", "rgb": "#001f3f", "color_group": null }]
}
```

Gender values: `m` (mens), `w` (womens), `u` (unisex).

### `GET /api/active_products`
Catalog of all sellable products. **Minimal payload** — no images, names, or prices.

```json
[
  {
    "id": 101, "shopify_id": "gid://shopify/Product/12345",
    "color_id": 5, "product_line_id": 10, "style_id": 15, "category_id": 3,
    "on_site": true, "in_store": true,
    "slug": "navy-crew-neck-tee", "url": "/navy-crew-neck-tee",
    "code": "CREW-NAVY-001", "sku_root": "CREW-NAVY"
  }
]
```

Use `slug` to join to Shopify Storefront `product(handle: <slug>)` for images, names, prices, variants. Use `code` when interacting with cart/restock endpoints.

### `GET /api/products/:id/sold_with`
Frequent-co-purchase recommendations. `:id` may be a numeric product ID or a slug.

```json
{
  "code": "CREW-NAVY-001", "id": 101, "product_line_id": 10, "category_id": 3,
  "sold_with": [
    { "code": "JEAN-INDIGO-001", "id": 102, "product_line_id": 11,
      "category_id": 4, "sold_count": 42, "last_sold_at": "2026-04-20T15:30:00Z" }
  ]
}
```

### `GET /api/product_lines/:id/sold_with`
Same shape, scoped to product lines (style families).

## Inventory

### `GET /api/inventory?token=<inventory_api_key>` *(CSV, streaming, partner-only)*

```
sku,count
CREW-NAVY-SM,5
CREW-NAVY-MD,12
```

`count` is sellable units across all locations after safety thresholds (warehouse total + max(0, retail total − all-retail safety threshold) − pending new order_items). 5-minute server-side cache. **No per-location breakdown.**

Without an inventory token, query Shopify Storefront `availableForSale` and `quantityAvailable` instead.

## Stores / locations

### `GET /api/locations`
Returns all sellable-online locations with addresses, hours, and coordinates. No auth.

```json
[
  {
    "id": 1, "name": "NYC Flagship", "short_name": "NYC",
    "address_line1": "123 Main St", "address_line2": "Suite 100",
    "address_city": "New York", "address_state": "NY",
    "address_zip": "10001", "address_country": "US",
    "hours": "Mon-Fri 10-7, Sat 11-6, Sun 12-5",
    "pickup_enabled": true,
    "address_phone": "212-555-1234", "email": "nyc@example.com",
    "coordinates": [40.7128, -74.0060]
  }
]
```

`coordinates` is `[latitude, longitude]`. Use Haversine to compute distance from the customer's zip.

For per-store stock of a specific SKU, use Shopify Storefront `productVariant.storeAvailability` — Pima doesn't expose this publicly.

## Account

### `POST /api/register`
```
email=<email>&password=<password>&cart_items[][productId]=&cart_items[][size]=&cart_items[][quantity]=
```
Returns `{ "jwt": "...", "account": { ... } }`.

### `POST /api/login`
```
auth[email]=<email>&auth[password]=<password>
```
Returns `{ "jwt": "...", "account": { ... } }` on success, `{ "error": "incorrect" }` on failure.

### `GET /api/account`  *(auth required)*
Current customer + cart + saved sizes/preferences.

```json
{
  "jwt": "...",
  "account": {
    "id": 123, "email": "...", "firstName": "...", "lastName": "...", "name": "...",
    "guest": false, "referralId": "...",
    "preferences": { /* arbitrary JSON */ },
    "sizes":       { /* e.g. {"shirt":"M","pant":"32x32","short":"M","shoe":"10.5"} */ },
    "blocklisted": false,
    "cart":     { /* Order object — see below */ },
    "shipping": { /* CustomerAddress */ },
    "waitlistProducts":      ["PRODUCT-CODE-1"],
    "restockNotifications":  [{ "size": "M", "product": "PRODUCT-CODE-1" }],
    "stripe_customer":       { /* Stripe customer object */ }
  }
}
```

### `POST /api/account`  *(auth required, used to update profile)*
Body params (all optional):
- `customer[email]`, `customer[first_name]`, `customer[last_name]`
- `customer[sizes]` — JSON-stringified object
- `customer[preferences]` — JSON-stringified object
- `shipping[address_line1]`, `shipping[address_city]`, `shipping[address_state]`, `shipping[address_zip]`, `shipping[address_country]`, `shipping[address_phone]`

### `POST /api/restock_notifications`
Subscribe to a size. Auth optional; without it, supply `email` and a guest customer is created.

```
product_code=<code>&size_name=<size>&email=<email-if-guest>
```

## Cart

### `POST /api/update_cart`
No auth required (creates a guest cart). Two modes:

**Add a single item** (preserves existing cart):
```
items[0][productId]=101&items[0][size]=M&items[0][quantity]=1&items[0][type]=single
```
Or by code:
```
items[0][product_code]=CREW-NAVY-001&items[0][size_name]=M&items[0][quantity]=1
```
`type` may be `single`, `product`, or `gift-certificate`.

**Replace the whole cart** — supply all desired items in one call; the cart is reset to that exact set.

Response: same shape as `GET /api/account` (returns the updated `account.cart`).

### `POST /api/add_coupon`
```
code=SPRING25
```
Returns the updated order (with `discount` applied).

### `POST /api/add_coupon_or_customer_credit`
Same shape — accepts either a coupon code or a customer-credit code. Use this when you don't know which the customer typed.

## Checkout

### `POST /api/purchase`

Body (form-urlencoded):
- `order[stripe_token]` — required unless `order[use_existing_card]=true` (auth required for that path)
- `order[shipping_rate_code]` — optional shipping selection
- `order[new_customer_address][email]`, `[name]`, `[address_line1]`, `[address_city]`, `[address_state]`, `[address_zip]`, `[address_country]`, `[address_phone]`
- `order[items][N][...]` — optional final cart sync before charging
- `order[campaign_params]` — optional UTM/marketing data

Success: completed `Order` JSON (status: `processing`, `completed_at` set).
Failure: `{ "errors": { ... }, "order": {...}, "to_capture_amount": 5000 }`.

**Recommended pattern for agent-driven shopping:** instead of calling `/api/purchase` directly, build the cart via `/api/update_cart` then surface a Shopify checkout URL (`https://www.buckmason.com/cart/<variant_id>:1,<variant_id>:1`) for the customer to complete in their browser. Only call `/api/purchase` if the customer has explicitly authorized a card-on-file charge in the same turn.

## Orders

### `GET /api/orders`  *(auth required)*
Paginated past orders. `?page=2` for pagination.

### `GET /api/orders/:id`
Single order by code or numeric ID. Auth required if the order belongs to a logged-in customer.

### `GET /api/order_history?token=<jwt or order_code>`
Customer's last year of orders, with shipment + tracking + estimated delivery date. Pass `?token=<jwt>` for the customer, or `?order_code=<code>` for a single guest order.

```json
[
  {
    "id": 456, "code": "ORD-ABC123", "status": "completed",
    "total": 9720, "rms_status": "delivered", "completed_at": "2026-04-20T10:00:00Z",
    "location": "NYC Flagship", "estimated_delivery_date": "2026-04-24",
    "items": [
      { "id": 1001, "status": "shipped",
        "product": "Navy Crew Neck Tee", "color": "Navy", "sku": "CREW-NAVY-SM",
        "size": "S", "original_paid_price": 9720, "tax": 720,
        "thumb_url": "https://cdn.example.com/uploads/product_image/file/123/thumb.jpg",
        "rms_returnable": true, "rms_status": "delivered" }
    ],
    "shipments": [
      { "id": 789, "status": "shipped", "tracking_code": "1Z…",
        "tracking_url": "https://…", "shipped_at": "2026-04-21T08:00:00Z",
        "estimated_delivery_date": "2026-04-24",
        "items": [ /* matching items */ ] }
    ]
  }
]
```

This is the cleanest endpoint for **wardrobe seeding** — every item the customer has bought, with image thumbnails, sizes, and SKUs.

## Common JSON shapes

### `Order`
```json
{
  "id": 456, "pos": false, "code": "ORDER-CODE",
  "status": "pending|processing|completed|cancelled",
  "subtotal": 10000, "discount": 1000, "tax": 720, "shipping_fee": 0, "total": 9720,
  "completed_at": "2026-04-20T10:00:00Z",
  "items": [ /* OrderItem[] */ ],
  "exchangeable": true
}
```
All money fields are **integer cents**. Divide by 100 for display.

### `OrderItem`
```json
{
  "id": 1001, "product": "Navy Crew Neck Tee", "color": "Navy", "color_code": "#001f3f",
  "sku": "CREW-NAVY-SM", "size": "S", "quantity": 1,
  "original_paid_price": 9720, "status": "new|pending|shipped|cancelled",
  "tax": 720, "thumb_url": "https://cdn.example.com/uploads/product_image/file/123/thumb.jpg"
}
```

## Error catalog

| Endpoint | Condition | Response |
|---|---|---|
| `POST /api/login` | bad creds | `{ "error": "incorrect" }` |
| `POST /api/register` | missing fields | `{ "errors": "Missing email or password" }` |
| `POST /api/update_cart` | unknown product | `{ "errors": { "inventory": "Sorry, we couldn't find <code>" } }` |
| `POST /api/purchase` | empty cart | `{ "errors": { "inventory": "Your cart is empty." } }` |
| `GET /api/inventory` | missing/wrong token | 403 plain text "Unauthorized" |
| `GET /api/products/:id/sold_with` | not found | `{}` (empty object — not an error) |

## What this API does *not* expose (use Shopify Storefront instead)

- Per-store stock for a SKU
- Product names, prices, descriptions, images on the catalog endpoint
- Search/filter (autocomplete, faceted search)
- Storefront content (collections, editorial, recommendations beyond `sold_with`)

For all of these, use the Shopify Storefront GraphQL API at `https://www.buckmason.com/api/<api-version>/graphql.json` with a Storefront access token, joining on the Pima `slug` ↔ Shopify `handle`.
