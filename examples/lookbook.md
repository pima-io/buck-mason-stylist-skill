# Worked example: lookbook + cart

**Customer says:** "Build me a 3-look lookbook for the Sonoma wedding, then a cart for look 2."

## 1. Load context

- `profile.md` → `gender: m`, sizes, fits, reference photo URL, `pima_live_key`, `home_zip`
- `wardrobe.md` → owned items
- `events.md` → match "Sonoma wedding"

```yaml
- name: Sarah & James wedding
  date: 2026-05-30
  location: Sonoma County, CA
  setting: outdoor vineyard ceremony, dinner under string lights
  dress_code: smart casual / cocktail
```

Apply `references/seasons.md`: late spring + NorCal coast/inland → mild + foggy evenings; smart casual → sport coat + dress shirt + trouser + suede chukka or dress shoe; palette → olive/stone/tobacco/indigo.

Get a season-aware capsule recommendation (one call):

```
GET /mcp/recommend?key=<key>&gender=m&occasion=wedding&dress_code=smart_casual&season=spring&near_zip=94110&radius_mi=25&sizes[shirt]=L&sizes[pant]=32x32&sizes[shoe]=10.5&sizes[jacket]=L
```

Response gives `capsule: [{slot: 'sport_coat', products: [...]}, {slot: 'shirt', ...}, {slot: 'pant', ...}, {slot: 'shoe', ...}]` — each product summary already includes `nearby_in_stock`, image, price.

## 2. Compose 3 outfits

Cross-reference wardrobe (`wardrobe.example.md`):
- Has: navy sport coat ✓, suede chukka ✓, indigo jean
- Gap: dress shirt finer than oxford; wool/wool-blend trouser; possibly a tie/pocket square

Three looks:

| Look | Sport coat | Shirt | Pant | Shoe | Accessory |
|---|---|---|---|---|---|
| 1 — ceremony classic | navy (owned) | white poplin | stone wool trouser | brown suede dress shoe | navy knit tie |
| 2 — daytime relaxed | none | pale-blue poplin | tobacco chino | suede chukka (owned) | none |
| 3 — dinner-only | navy (owned) | white poplin | indigo jean (owned, dark) | brown suede dress shoe | pocket square |

For each item not in the wardrobe, the `/mcp/recommend` response already has `image_url`, `price`, `nearby_in_stock`. If you need finer detail (full image gallery, per-store counts), call `GET /mcp/products/<slug>?key=…&near_zip=…&radius_mi=25`.

## 3. Generate try-on images

For each look, follow `references/image-generation.md`:

```python
from openai import OpenAI
client = OpenAI()

reference = open(profile["reference_photo_local"], "rb")

for look_num, look in enumerate(LOOKS, start=1):
    product_images = [open(p["flatlay_path"], "rb") for p in look["items"]]
    prompt = build_prompt(
        outfit=look["description"],
        setting=SETTINGS[look_num - 1],
        composition=COMPOSITIONS[look_num - 1],
    )
    result = client.images.edit(
        model="gpt-image-1",
        image=[reference] + product_images,
        prompt=prompt, size="1024x1536", quality="high", n=1,
    )
    save(f"lookbook/2026-05-30-sonoma-wedding/looks/look-{look_num}.png",
         b64decode(result.data[0].b64_json))
```

Settings + compositions for a Sonoma vineyard wedding:

```python
SETTINGS = [
    "outdoor vineyard ceremony aisle, late afternoon, soft warm side-light, white folding chairs visible in soft focus",
    "vineyard exterior between rows of vines, midday, dappled sunlight, walking",
    "long dinner table under string lights at dusk, warm bulb glow, soft fog, candid",
]
COMPOSITIONS = [
    "full-body, three-quarter turn, hands relaxed, eye-level 35mm",
    "medium-wide, walking toward camera, hand in pocket, slight smile, 50mm",
    "seated at table edge, leaning slightly forward in conversation, 50mm shallow depth",
]
```

## 4. Assemble the lookbook markdown

```
lookbook/2026-05-30-sonoma-wedding/
  profile.jpg                         (cached)
  products/
    poplin-white.jpg
    wool-trouser-stone.jpg
    dress-shoe-brown.jpg
    knit-tie-navy.jpg
    poplin-pale-blue.jpg
    chino-tobacco.jpg
    pocket-square-tonal.jpg
  looks/
    look-1.png
    look-2.png
    look-3.png
  lookbook.md
  cart-look-2.txt
```

`lookbook.md` body (rendered to the customer):

```markdown
# Sarah & James, Sonoma — May 30

> AI-generated previews; fit and fabric may vary slightly. Free returns within 30 days.

## Look 1 — Ceremony classic
![](looks/look-1.png)
- Navy sport coat (you own it)
- White poplin dress shirt — $98 — [shop](https://www.buckmason.com/products/poplin-white)
- Stone wool trouser — $148 — [shop](...)
- Brown suede dress shoe — $228 — [shop](...)
- Navy knit tie — $58 — [shop](...)
**Total new: $532** — [Build cart for Look 1](#)

## Look 2 — Daytime relaxed
![](looks/look-2.png)
- Pale-blue poplin dress shirt — $98 — [shop](...)
- Tobacco chino — $128 — [shop](...)
- Suede chukka (you own it)
**Total new: $226** — [Build cart for Look 2](#)

## Look 3 — Dinner-only
![](looks/look-3.png)
- Navy sport coat (you own it)
- White poplin dress shirt (Look 1)
- Indigo jean (you own it)
- Brown suede dress shoe (Look 1)
- Tonal pocket square — $32 — [shop](...)
**Total new: $32** — [Build cart for Look 3](#)
```

## 5. Build the cart for Look 2

Look 2 needs 2 new items: pale-blue poplin (size L) + tobacco chino (size 32x32). One stateless call:

```
POST https://www.buckmason.com/mcp/cart?key=<key>
Content-Type: application/json

{ "items": [
    { "slug_or_code": "poplin-pale-blue", "size": "L",     "qty": 1 },
    { "slug_or_code": "tobacco-chino",    "size": "32x32", "qty": 1 }
] }
```

Response:
```json
{
  "checkout_url": "https://www.buckmason.com/cart/9999:1,9998:1",
  "subtotal_cents": 22600, "subtotal": "$226.00",
  "items": [
    { "product": { "name": "Pale-blue Poplin Dress Shirt",
                   "url": "https://www.buckmason.com/products/poplin-pale-blue" },
      "sku": "POPLIN-PALE-BLUE-L", "size": "L", "quantity": 1, "unit_price": "$98.00" },
    { "product": { "name": "Tobacco Chino",
                   "url": "https://www.buckmason.com/products/tobacco-chino" },
      "sku": "CHINO-TOBACCO-32x32", "size": "32x32", "quantity": 1, "unit_price": "$128.00" }
  ]
}
```

Render to the customer:

```
Cart for Look 2:
  Pale-blue Poplin Dress Shirt — L — $98.00
  Tobacco Chino — 32x32 — $128.00
  Subtotal $226.00 (tax + shipping calculated at checkout)

Checkout (in your browser): https://www.buckmason.com/cart/9999:1,9998:1
```

## 6. Customer says "yes, charge my card on file"

Only proceed if:
1. Customer is authenticated (JWT belongs to a registered customer, not a guest).
2. They have a saved card (`account.stripe_customer.default_source` exists).
3. They've explicitly authorized in the same turn ("charge it" / "go ahead and pay").

Restate the total in plain English, then:

```
POST https://www.buckmason.com/api/purchase
Authorization: Bearer <jwt>
  order[use_existing_card]=true
  order[shipping_rate_code]=standard
```

Response on success:
```json
{
  "id": 9921, "code": "ORD-AB12CD", "status": "processing",
  "completed_at": "2026-04-24T18:30:00Z", "total": 24634, ...
}
```

Confirm to the customer: order code, total charged, expected delivery from `estimated_delivery_date` (later visible via `GET /api/order_history`).

If the customer is a guest or there's no saved card, **do not** ask for card details — produce the Shopify checkout URL instead and let them complete it in their browser.
