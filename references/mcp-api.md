# Pima MCP endpoints (`/mcp/*`)

A purpose-built, agent-friendly surface that wraps the same Pima data exposed under `/api/*`, but in shapes designed for stylists/shopping agents:

- One call gives you names, prices, images, gender, sizes, online + per-store stock.
- A `near_zip=…&radius_mi=25` param does the geocode + haversine for you.
- "Seasonality" is approximated by recently set-live products until the item-master/`ProductAttributes` work lands; the same endpoints will swap to richer signals (style: spring/summer, fabric weight, occasion tags) without breaking the contract.

## Common conventions

- **Base URL**: `https://pima.io` (the Pima MCP host). For Buck Mason all paths are `https://pima.io/mcp/buckmason/...`.
- **Tenant selection**: every path is prefixed with `/mcp/<company_slug>/...`. For Buck Mason, the slug is `buckmason`. Slugs are derived from the company name via `name.parameterize` (so "Buck Mason" → `buckmason`).
- **Auth**: none. All endpoints are public — no key, header, or cookie required.
- **Money**: every endpoint returns both `*_cents` (integer) and a pre-formatted string (`"$98.00"`).
- **Gender**: pass `?gender=m` (or `male`/`men`/`mens`) — also accepts `w` and `u` (unisex). Omit for "any gender" results.
- **Geocoding**: pass `?near_zip=94110&radius_mi=25` to any endpoint that supports it; the server geocodes the zip (Geocoder gem, 30-day cache), filters by radius, and sorts by distance.

## `GET /mcp/manifest`

Self-describing endpoint catalog. Useful for an MCP server or agent to discover available actions without hardcoding.

```
GET /mcp/<company_slug>/manifest
```

Returns `{ name, company, version, endpoints: [...], docs }`.

## `GET /mcp/products`

Rich, filterable product list. Replaces `/api/active_products` for shopping flows.

| Param | Notes |
|---|---|
| `gender` | `m` / `w` / `u` (also accepts `male`/`female`/`unisex`/`men`/`women`/`mens`/`womens`) |
| `category` | category name (case-insensitive) or numeric id |
| `style` | style name or id |
| `color` | color name or id |
| `q` | free-text search (matches name, full_name, code, sku_root) |
| `recently_live` | `true` → restrict to products created in the last `recently_live_days` (default 30) and sort newest first |
| `recently_live_days` | integer, 1–365 |
| `near_zip`, `radius_mi` | enables `nearby_in_stock` boolean per product (cheap heuristic — checks first SKU at each in-radius store) |
| `in_stock_only` | when truthy, also computes `online_in_stock` per product |
| `min_price`, `max_price` | dollars (floats) |
| `page`, `per_page` | default 30, max 100 |

Response:

```json
{
  "page": 1, "per_page": 30, "total": 412, "total_pages": 14,
  "products": [
    {
      "id": 101, "code": "DAILY-OLIVE-001", "slug": "daily-shirt-olive",
      "name": "Daily Shirt — Olive", "full_name": "Daily Shirt — Olive",
      "gender": "m",
      "category": "Tops", "style": "Daily Shirt", "product_line": "Daily Shirt",
      "color": "Olive", "color_rgb": "#5b6242",
      "price_cents": 9800, "price": "$98.00",
      "on_sale": false, "sale_price_cents": null,
      "url": "https://www.buckmason.com/products/daily-shirt-olive",
      "image_url": "https://cdn.../products/daily-olive.jpg",
      "image_count": 6,
      "published_at": "2026-04-15T17:22:00Z",
      "sizes": ["XS","S","M","L","XL","XXL"],
      "online_in_stock": true,
      "nearby_in_stock": true
    }
  ]
}
```

## `GET /mcp/products/:id`

Single product by `slug`, `code`, or numeric id.

```
GET /mcp/<company_slug>/products/daily-shirt-olive?near_zip=94110&radius_mi=25
```

Response is the summary plus:

- `description` (markdown)
- `images[]` — `{ url, type, position }` (full image gallery)
- `variants[]` — one entry per SKU with per-location stock if `near_zip` was passed:

```json
{
  "sku": "DAILY-OLIVE-L",
  "size": "L",
  "shopify_variant_id": "gid://shopify/ProductVariant/9999",
  "online_count": 12,
  "locations": [
    { "id": 7, "name": "Hayes Valley", "distance_mi": 0.8,
      "pickup_enabled": true, "in_stock": true, "count": 4,
      "address_city": "San Francisco", "address_state": "CA" }
  ]
}
```

## `GET /mcp/stock/:sku`

Per-SKU breakdown. Use when you already know the exact SKU (e.g. from the variants list above) and want a fast availability snapshot.

```
GET /mcp/<company_slug>/stock/DAILY-OLIVE-L?near_zip=94110&radius_mi=25
```

Response: same shape as one entry of `variants[]` above (sku, size, online_count, locations[]).

## `GET /mcp/locations`

All sellable-online locations. With `near_zip`, filtered + sorted by distance.

| Param | Notes |
|---|---|
| `near_zip`, `radius_mi` | optional |
| `pickup_only` | `true` → only `pickup_enabled` stores |

Response: `{ locations: [{ id, name, short_name, pickup_enabled, sellable_online, coordinates: [lat,lng], distance_mi, address_*, phone, hours }] }`.

## `GET /mcp/seasonal`

Recently set-live products as a stand-in for season-aware "what's new this season" until the FY26 item-master attributes ship. Grouped by category.

| Param | Default | Notes |
|---|---|---|
| `gender` | none | filter |
| `category` | none | filter |
| `days` | 30 | window in days (1–365) |
| `limit` | 24 | total products returned (1–100) |

Response:

```json
{
  "generated_at": "2026-04-24T18:00:00Z",
  "window_days": 30,
  "gender": "m",
  "categories": [
    { "category": "Tops", "count": 8, "products": [ /* product summaries */ ] },
    { "category": "Bottoms", "count": 4, "products": [ /* … */ ] }
  ]
}
```

When the item-master branch lands, this endpoint will additionally expose `season`, `fabric_weight`, and `occasion_tags` per product without changing the wrapper shape.

## `GET /mcp/categories`

Taxonomy filtered by gender. Lighter than `/api/product_structure` for the agent's purposes.

```
GET /mcp/<company_slug>/categories?gender=m
```

Returns `{ gender, categories: [{ id, name, styles: [{ id, name, product_lines: [{ id, name, gender }] }] }] }`.

## `GET /mcp/recommend`

Best-effort capsule suggestion for a context. Heuristic — pairs the customer's gender + occasion + sizes with recently-active products in the right category slots.

| Param | Notes |
|---|---|
| `gender` | `m`/`w`/`u`. When `m` or `w`, unisex products are also included. |
| `occasion` | `wedding`, `business`, `travel`, `casual` (default) |
| `dress_code` | `formal`, `cocktail`, `smart_casual`, `business_casual`, `casual` |
| `season` | `spring`/`summer`/`fall`/`winter` — defaults from server time |
| `near_zip`, `radius_mi` | for in-stock signal |
| `sizes[shirt]`, `sizes[pant]`, `sizes[short]`, `sizes[shoe]`, `sizes[jacket]` | when present, the recommended item's `nearby_in_stock` is computed for the size that matches that slot |
| `budget` | total dollar cap across the whole capsule (e.g. `400`). When set, the algorithm picks the cheapest in-stock item per slot first; slots that don't fit the remaining budget are skipped and reported in `dropped_slots`. |
| `max_price_per_item` | per-item dollar cap (e.g. `150`); independent of `budget`. |

Response:

```json
{
  "gender": "m", "occasion": "wedding", "dress_code": "smart_casual",
  "season": "spring", "generated_at": "2026-04-24T18:00:00Z",
  "budget_cents": 40000, "budget": "$400.00",
  "max_price_per_item_cents": null, "max_price_per_item": null,
  "spent_cents": 38400, "spent": "$384.00",
  "remaining_cents": 1600, "remaining": "$16.00",
  "dropped_slots": [
    { "slot": "shoe", "reason": "over budget", "cheapest_cents": 22800, "cheapest": "$228.00" }
  ],
  "capsule": [
    { "slot": "sport_coat", "products": [ /* up to 3 product summaries; first is the chosen pick */ ] },
    { "slot": "shirt",      "products": [ /* … */ ] },
    { "slot": "pant",       "products": [ /* … */ ] }
  ]
}
```

When `budget` is set, the first product in each slot's `products` array is the one credited against the budget. Use the others as alternates if the customer wants to swap.

## `POST /mcp/<company_slug>/cart`

Stateless. Resolves items, returns a Shopify cart permalink the customer opens in their browser to checkout. No JWT, no Pima session, no card handling.

Body (JSON or form-encoded):

```json
{
  "items": [
    { "slug_or_code": "daily-shirt-olive", "size": "L", "qty": 1 },
    { "slug_or_code": "tobacco-chino",     "size": "32x32", "qty": 1 }
  ],
  "coupon": "SPRING25",
  "pickup_location_slug": "abbot-kinney",   // optional — see "In-store pickup" below
  "pickup_location_id":   2                  // alternative; takes precedence if both present
}
```

Response:

```json
{
  "checkout_url": "https://www.buckmason.com/cart/9999:1,9998:1?discount=SPRING25&attributes[Pickup-Location]=Abbot%20Kinney%20Men%27s",
  "coupon": "SPRING25",
  "subtotal_cents": 22600,
  "subtotal": "$226.00",
  "pickup": {
    "location_id": 2,
    "location_name": "Abbot Kinney Men's",
    "address": "1320 Abbot Kinney Blvd, Venice, CA 90291",
    "all_items_in_stock": true
  },
  "items": [
    { "product": { "id": 101, "code": "DAILY-OLIVE-001", "slug": "daily-shirt-olive",
                   "name": "Daily Shirt — Olive",
                   "url": "https://www.buckmason.com/products/daily-shirt-olive" },
      "sku": "DAILY-OLIVE-L", "size": "L", "quantity": 1,
      "unit_price_cents": 9800, "unit_price": "$98.00" }
  ]
}
```

If `pickup_location_*` is omitted, the `pickup` block is absent from the response and the `checkout_url` has no `Pickup-Location` attribute (customer picks ship-vs-pickup at Shopify checkout).

### In-store pickup contract

When `pickup_location_slug` or `pickup_location_id` is present:

1. Server resolves the location by slug (`name.parameterize`) or id; 404 if unknown.
2. Server checks that the location is `pickup_enabled = true`; 422 `{ "error": "pickup not available at <store>" }` if not.
3. Server checks every requested SKU has `>= qty` available units at that location. If any item is short:
   - Default: 422 `{ "error": "items not in stock for pickup at <store>", "shortages": [{ "sku": "...", "wanted": 1, "available": 0 }, ...] }` — agent should fall back to ship-it or split the cart.
   - With `?allow_pickup_partial=true`, the response is 200 but `pickup.all_items_in_stock = false` and `pickup.shortages` is populated — agent decides what to do.
4. The `checkout_url` appends `?attributes[Pickup-Location]=<URL-encoded location.name>` (Shopify cart attribute). When the customer clicks the link, Shopify pre-selects the pickup option and the named store at the shipping step.

**Discovery.** To enumerate pickup-enabled stores near the customer, use `/mcp/<company_slug>/locations?near_zip=<zip>&pickup_only=true`. Each location's `id` and `short_name` are usable as `pickup_location_id` / `pickup_location_slug`.

**Implementation note.** The pickup contract is a planned extension to `/mcp/buckmason/cart` — the slug resolution, stock check, and `attributes[Pickup-Location]=` URL-encoding are not yet live in Pima as of v0.1.0 of this skill. Until then, the agent should fall back to building a ship-default cart and verbally telling the customer to choose pickup at checkout. Track Pima implementation: search the Pima repo for `pickup_location_slug`.

For card-on-file checkouts (auth-required), continue to use `POST /api/purchase` after building a Pima cart via `POST /api/update_cart`. `POST /mcp/cart` is for the common, safer pattern of handing the user a checkout link.

## Error responses

| Condition | Response |
|---|---|
| Unknown `company_slug` | 404 `{ "error": "No company with slug: <slug>" }` |
| `:id` lookup fails on `/mcp/<company_slug>/products/:id` or `/mcp/<company_slug>/stock/:sku` | 404 |
| `POST /mcp/cart` with no resolvable items | 422 `{ "error": "no items resolved", "items": [...] }` |
| `POST /mcp/cart` with unsynced SKUs | 422 `{ "error": "one or more SKUs are not synced to Shopify", "skus": [...] }` |
| `near_zip` that fails to geocode | request proceeds with no distance filter (warning printed in dev) |

## Notes on what's coming

- **Item-master** branch will add `season`, `fabric_weight`, `occasion_tags`, `silhouette` directly on `Product`/`ProductAttribute`. Endpoints will gain the new filter params (`?season=spring`, `?occasion=wedding`, `?fabric=linen`) and surface the values in `product_summary`.
- **Per-look saved bundles** (so the agent can hand back a stable `/mcp/<company_slug>/cart/:id` URL instead of a Shopify permalink) will land alongside item-master.
- **Per-store reservations** for in-store pickup — currently the skill should recommend pickup but leave the actual reservation to the customer in-app.
