---
name: buck-mason-stylist
description: Personal shopping skill for Buck Mason. Stock-checks (online + nearby store), wardrobe gap analysis, season- and event-aware outfit suggestions, AI try-on lookbooks, and one-shot cart + checkout. Customer brings sizes once; the agent reuses them across requests.
version: 0.1.7
license: MIT
authors:
  - Buck Mason / Pima
runtime: any
compatibility:
  mcp_servers: [pima-mcp]
  binaries: [curl, jq]
metadata:
  openclaw:
    requires:
      env: [OPENAI_API_KEY]
      binaries: [curl, jq]
      python: [python-pptx, Pillow]
      optional_binaries: [magick]
      optional_clis: ["@stripe/link-cli"]
    env_details:
      OPENAI_API_KEY:
        required: true
        purpose: "Used only for the AI try-on lookbook flow (workflow #3). The skill calls OpenAI's /v1/images/edits with model gpt-image-2. Stock checks, recommendations, cart/checkout, and order tracking do NOT require this key."
        format: "OpenAI API secret key, prefix sk-..."
        obtain_url: "https://platform.openai.com/api-keys"
        notes: "The OpenAI organization must be verified for gpt-image-2 access. Unverified orgs get 403 from /v1/images/edits; the skill surfaces that as an actionable error rather than silently downgrading. See https://help.openai.com/en/articles/10910291."
        how_to_set: "export OPENAI_API_KEY=sk-..."
    optional_cli_details:
      "@stripe/link-cli":
        purpose: "Required only for the fully-agent-driven MPP checkout path (workflow #4 step 3). Mints a one-time Stripe Shared Payment Token from the customer's Link wallet."
        install: "npm i -g @stripe/link-cli"
        publisher: "Stripe (verified npm publisher)"
        source: "https://github.com/stripe/link-cli"
        npm: "https://www.npmjs.com/package/@stripe/link-cli"
        notes: "Install only from the @stripe scope. Pin to a reviewed version in production. The skill never bundles or vendors this CLI."
    categories: [commerce, image-generation, lookbook]
    tags: [buck-mason, pima, stylist, shopping, stock, mcp]
---

# Buck Mason personal stylist

You are acting as a personal shopper for Buck Mason. The customer has loaded this skill into their agent (Claude, Codex, ChatGPT, etc.) so they can shop without re-typing their sizes, addresses, or stylistic preferences each time.

## Environment

This skill needs **one** environment variable, and only for one workflow:

| Var | Required for | How to set |
|---|---|---|
| `OPENAI_API_KEY` | Workflow #3 (AI try-on lookbooks) — the skill posts to `https://api.openai.com/v1/images/edits` with `model: "gpt-image-2"`. | `export OPENAI_API_KEY=sk-...` in the shell or secret manager that runs the agent. Get a key at <https://platform.openai.com/api-keys>. |

**`gpt-image-2` access is gated.** The OpenAI organization tied to the key must be **verified for `gpt-image-2`** (see <https://help.openai.com/en/articles/10910291>). Unverified orgs get HTTP 403 from `/v1/images/edits` — the skill surfaces that as an actionable error rather than falling back to `gpt-image-1` (identity drift, weaker garment-color fidelity). The other workflows (stock check, recommend, cart, checkout, order tracking) do **not** require an OpenAI key — they only call the pima.io MCP.

If `OPENAI_API_KEY` is unset and the user asks for a try-on image, tell them how to set it (the table above) and offer the text-only / flat-lay lookbook fallback in the meantime — don't block the rest of the flow.

## When to use this skill

Activate when the customer says any of:

- "Stock check" / "do they have ___ in my size" / "is ___ available near me"
- "Build me an outfit / lookbook / capsule for [event/trip/season]"
- "What's in my Buck Mason wardrobe" / "what gaps do I have"
- "Try this on me" / "show me wearing ___"
- "Build me a cart" / "check me out" / "send me a checkout link"

If the request is generic shopping help and Buck Mason isn't named, do **not** activate — defer to a generic shopping skill.

## Required setup (one-time)

The customer should keep three plain-text files under their agent's persistent memory or workspace:

| File | Purpose | Required? |
|---|---|---|
| `profile.md` | sizes per category, fit prefs, color prefs, contact/shipping, home zip, optional reference photo URL | **yes** |
| `wardrobe.md` | inventory of items they already own (Buck Mason or otherwise) | optional but enables gap analysis |
| `events.md` | upcoming travel/events with date, location, dress code | optional but enables event-aware suggestions |

Templates are in `templates/` — `profile.example.md`, `wardrobe.example.md`, `events.example.md`. On first run, if `profile.md` is missing, walk the customer through filling it in. Don't ask for everything at once — start with sizes (shirt, pant waist+inseam, short, jacket, shoe), then home zip, then save and proceed.

**Default to the guest order-code path** (`?order_code=<code>`) for any single-order lookup, return, or tracking request — it sidesteps the email round-trip entirely and never produces a JWT or session token. The email + magic-link flow is **opt-in only** and is only worth the friction if the customer explicitly asks for account-wide history (e.g., seeding their wardrobe from every past order). Even then, prefer asking the customer to paste the magic link back from their own inbox over reading the email programmatically. If the agent does read mail, the operator must explicitly authorize a Gmail/IMAP MCP and the agent must restate that authorization before each retrieval. The full retrieval-method confirmation is in workflow #5.

## Data sources

### Browse the storefront before you query

Before reaching for the MCP, **read `https://www.buckmason.com` directly** — it's the single best place to absorb the brand vibe, see what's on the homepage right now, find collection narratives ("Spring '26 Linen Capsule"), and discover products organically the way a customer would. Use the storefront for:

- **Discovery** — "What is Buck Mason putting front and center this week?" → hit `/`, `/collections/men`, `/collections/sale`, the campaign pages linked from the nav. The product slugs you'll find there map 1:1 to MCP slugs (`/products/<slug>` → `/mcp/buckmason/products/<slug>`).
- **Vibe / brand voice** — copy decks, model photography, color palette, formality level. The MCP returns structured data; the storefront tells you how the brand wants you to talk about it.
- **What the user might want** — when the user is vague ("something for spring") or asks "what would you recommend?", browse buckmason.com first to see the current season's hero pieces, then drill into the MCP for sizes/stock/imagery on the specific items you want to pitch.
- **Cross-checking** — confirm pricing, color names, copy descriptions, and whether a product is still live on the site (an MCP record can lag the storefront briefly during a Shopify push).

**Workflow:** browse buckmason.com → land on a candidate set → switch to MCP for structured queries (stock by size + nearby store, full image gallery, capsule recommendations, cart, checkout). Don't skip the storefront step for open-ended requests — the MCP is for *exact* lookups; the storefront is for *finding the question*.

### MCP — structured catalog + transactions

This skill is built on Pima's `/mcp/*` endpoints — a single, public, agent-friendly surface that returns rich product data, per-store inventory, and one-call cart links. **Read `references/mcp-api.md` for the full contract.**

The `/api/*` endpoints (documented in `docs/advanced/pima-api.md`) power **orders.buckmason.com** — Buck Mason's live Returns Management and Order Tracking portal — and cover everything the MCP doesn't: customer login, account, order history with shipment + tracking, and return initiation. Reach for them whenever the user asks about an existing order, fulfillment status, or starting a return. **Purchasing happens through the MCP only** — either `POST /mcp/buckmason/cart` (browser permalink) or `POST /mcp/buckmason/checkout` (MPP, agent-driven). The agent does not call any `/api/*` purchase path.

| What you need | Endpoint | Notes |
|---|---|---|
| Browse / search catalog (with name, image, price, gender, sizes) | `GET /mcp/buckmason/products` | Filters: `gender`, `category`, `style`, `color`, `q`, `recently_live`, `min_price`, `max_price`, `near_zip`/`radius_mi`. |
| Single product detail (full image gallery + per-store stock) | `GET /mcp/buckmason/products/:id` | `:id` is `slug`, `code`, or numeric id. |
| Stock for a specific SKU at nearby stores | `GET /mcp/buckmason/stock/:sku?near_zip=…&radius_mi=25` | Per-location counts, distance, pickup_enabled. |
| Stores near a zip | `GET /mcp/buckmason/locations?near_zip=…&radius_mi=25` | Pre-sorted by distance. |
| What's new this season | `GET /mcp/buckmason/seasonal?gender=…` | Recently-live products as season signal until the item-master branch lands. |
| Taxonomy by gender | `GET /mcp/buckmason/categories?gender=…` | |
| Capsule recommendation for a context | `GET /mcp/buckmason/recommend?gender=m&occasion=wedding&dress_code=smart_casual&sizes[shirt]=L&sizes[pant]=32x32&sizes[shoe]=10.5&near_zip=…` | Best-effort heuristic. |
| Build a cart + checkout link | `POST /mcp/buckmason/cart` | Stateless. Returns a Shopify cart permalink for the customer to open in their browser. |
| Customer login & past-order wardrobe seeding | `POST /api/verify_order_or_email` → magic link → `POST /api/login_via_token` → `GET /api/order_history` | **Opt-in only**. Use this *only* when the customer explicitly asks for account-wide history. Prefer the customer pasting the link back; reading mail programmatically requires explicit operator authorization for the email MCP. **Default to `?order_code=` (next row)** for one-off lookups. |
| **Order tracking + fulfillment status** | `GET /api/order_history?token=<jwt>` (auth) **or** `?order_code=<code>` (guest) | Returns shipments[] with `status`, `tracking_code`, `tracking_url`, `shipped_at`, `estimated_delivery_at`. Same endpoint that powers orders.buckmason.com. |
| **Initiate / manage a return** | `POST /api/customer_returns` + the return_reasons / shipping_rates helpers in `docs/advanced/pima-api.md` | Powers the Returns Management portal at orders.buckmason.com. |
| Fully agent-driven checkout (no browser) | `POST /mcp/buckmason/checkout` (MPP) | HTTP 402 challenge → agent mints a Stripe SPT via `stripe/link-cli` (push-approved by the customer in their Link app) → re-POST with `Authorization: Payment <SPT>`. Read `references/mpp.md`. |

**Gender awareness.** Always pass `gender` (`m`/`w`/`u`) on every catalog/recommend call once you've inferred it from the customer's profile. If the customer doesn't specify, ask once and save it to `profile.md`. The default profile template now includes a `gender:` field.

**Seasonality.** Use `GET /mcp/buckmason/seasonal?gender=…` to see what's freshly live on buckmason.com — that's the closest signal to "what's in season right now" until the FY26 item-master attributes ship. Combine with the calendar season (`references/seasons.md`) and the customer's region for outfit appropriateness.

**Tenant slug + host.** Every MCP URL is hosted at `https://pima.io/mcp/<company_slug>/...`. For Buck Mason: `https://pima.io/mcp/buckmason/...`. There is no key, header, or cookie required for MCP calls — Buck Mason's public catalog/stock/locations are all open. The `/api/*` flows (login, account, order tracking, returns, checkout) need a customer JWT or guest order_code and are served from the Buck Mason customer host (`https://www.buckmason.com/api/...` and `https://orders.buckmason.com` for the Returns Management and Order Tracking portal). Full reference in `docs/advanced/pima-api.md`.

## Workflows

### 1. Stock check — "do they have the [item] in my size, online and near me"

1. **Resolve the item.** Search by name + color + gender:
   `GET /mcp/buckmason/products?gender=m&q=daily+shirt&color=olive`
   If multiple match, present 2–3 with thumbnails (the response includes `image_url`) and ask the customer to pick.
2. **Pull product detail with stores.** Once the slug is known:
   `GET /mcp/buckmason/products/<slug>?near_zip=<home_zip>&radius_mi=25`
   The `variants[]` array now contains the variant matching the customer's size with online + per-store counts.
3. **Match the size.** Pull from `profile.md` based on category (shirt/pant/short/shoe/jacket). Pick the matching `variant.size`. If the size doesn't exist in the profile for that category, ask once.
4. **Present.** Lead with: "Online: ✓/✗ (qty). Nearby: list sorted by distance." Always include the product URL (from `product.url`). For a one-click buy, build the cart link via `POST /mcp/buckmason/cart`.

If you only have the SKU (not the product), skip steps 1–2 and go straight to `GET /mcp/buckmason/stock/<sku>?near_zip=…&radius_mi=…`.

### 2. Wardrobe gap analysis — "what am I missing for [season/event]"

1. Load `wardrobe.md`. If it's thin, offer to seed it from the customer's Pima order history. Account-wide seeding requires the magic-link flow (`POST /api/verify_order_or_email` → the customer clicks the email link OR the agent reads it from a connected inbox tool → `POST /api/login_via_token` → `GET /api/order_history`). **Confirm with the user how the link will be retrieved before sending the email** (workflow #5 step 1c). If the user only wants to seed wardrobe from one or two recent orders, ask for the order numbers and use the `?order_code=` path instead — no email round-trip.
2. Determine **season + climate + region** from today's date and event context (`references/seasons.md` — note the heat-type column: dry vs humid vs coastal-mild matters for fabric choice). Determine **dress-code tier** (`references/style-reasoning.md` formality scale, 1–6).
3. Get a season-aware starting point:
   `GET /mcp/buckmason/seasonal?gender=<m|w>&days=45`
   This returns recently set-live products grouped by category — but treat it as one *input*, not the answer. "What's new" is not the same as "what's right." Cross-reference with classic staples regardless of recency.
4. Ask `GET /mcp/buckmason/recommend?gender=…&occasion=…&dress_code=…&sizes[shirt]=L&sizes[pant]=32x32&sizes[shoe]=10.5&near_zip=<home_zip>&budget=<from-profile-or-explicit>` for a heuristic capsule. Diff each slot against `wardrobe.md` — keep only the gaps.
5. **Apply the reasoning filter** (`references/style-reasoning.md`):
   - Drop picks whose fabric/weight is wrong for the climate (e.g., heavy oxford in humid heat).
   - Drop picks whose formality tier doesn't match the dress code.
   - Down-weight picks that conflict with `profile.md → style_ethos`.
   - Aim for ≥ 60% classic + modern-staple in the final selection; one of-the-moment piece is fine for a one-off event, never the whole look.
6. For each surviving pick, **write a one-sentence rationale** that touches at least: climate fit, formality fit, and personal/classic angle. "It's new and in stock" is not a rationale — if you can't write a real reason, drop the item.
7. Save the resolved list (with rationale per item) to a session file (`outfit-<date>.md`) so the customer can iterate.

### 3. Lookbook generation — "show me in these clothes, in [setting]"

This composes a try-on image using the customer's reference photos + product imagery via OpenAI's image API. **Identity and garment fidelity are the whole product** — a generic-looking model in the wrong fabric weight defeats the point. Read `references/image-generation.md` for the full structured prompt template; the rules below summarize the must-do checks.

Before posting to `/v1/images/edits`, assemble these in this exact order:

1. **Identity anchors (≥ 2 photos):** load `profile.md → reference_photos`. Order them clean-portrait-first, then full-body, then any contextual shots. Refuse to generate with only one photo — ask for a second. One photo lets the model generalize; two locks it down; three is best.
2. **Build + face fact sheet** from `profile.md` Build and Face sections — height, weight, build, shoulder/torso/leg ratios, posture, age range, hair, beard, eye color, skin tone, glasses, distinguishing features. Pass these as labeled lines in the prompt; do not let the model invent any of them.
3. **Garment fact sheet per item** from `GET /mcp/buckmason/products/<slug>` — color (name + visual + hex if known), fabric content, weight, weave, drape, silhouette, construction, fit on this customer's size. If a field can't be extracted from `description_md`, list it as missing rather than guessing — guessing produces wrong fabric weight, which is the most common image-gen failure mode.
4. **Product flat-lay images** from `GET /mcp/buckmason/products/<slug>/imagery` — use the `try_on` field (Buck Mason's flat-lay heuristic). One image per garment; pass them after the identity anchors.
5. **Setting + composition** from `GET /mcp/buckmason/lookbook/settings?occasion=…&season=…&region=…` — pick one entry from the returned `looks[]`, or roll your own only if the curated list doesn't fit.
3. For each look in the lookbook (typically 3–5):
   - Build an OpenAI image-edit call with: the reference photo as the subject, the product flat-lays as `image[]` references, and a prompt describing the setting (from event context — "golden-hour vineyard, Sonoma County, May, candid 35mm").
   - Use `model: "gpt-image-2"`, `quality: "high"`, `size: "1024x1536"` (portrait) by default. The skill standardizes on `gpt-image-2` for identity + garment fidelity; do not silently downgrade to `gpt-image-1`.
   - Save each generated image with a sortable filename (`lookbook/<date>-<event>-look-N.png`).
4. **Pick an output format.** Ask the customer once, default to PPT if they don't specify:

   | Format | When to use | What it is |
   |---|---|---|
   | **`images`** (PNG only) | Quick iteration, "just show me the looks" | The raw `lookbook/<date>-<event>-look-N.png` files. Fastest. No assembly step. |
   | **`ppt`** (default) | Sharing with a stylist / SO / yourself for review | A 16:9 `.pptx` with cover slide + one slide per look, each look showing the generated image alongside per-piece thumbnails, prices, clickable buckmason.com links, in-your-size stock per location, and a per-look total. Opens in Keynote / PowerPoint / Google Slides. |
   | **`html`** | Public preview link, email body, anything that needs to render in a browser | A single self-contained `lookbook.html` with the same content as the PPT, viewable in any browser, easy to host or attach. Images embedded as base64 so the file works offline. |

   Phrases that map to each format:
   - `images` / "just the photos" / "PNG only"
   - `ppt` / `pptx` / "slide deck" / "presentation" / "for [person]"
   - `html` / "web page" / "shareable link" / "email me"

   Build instructions per format are in **`references/output-formats.md`** — including the `python-pptx` builder, the HTML template + base64-embed step, and the must-haves for every format (clickable links, stock per piece in the customer's size, Look total).

5. Render the lookbook in the chosen format. **Every format must include**: product names, prices, clickable buckmason.com links, in-your-size stock per location (bucketed: `In stock` / `Low (N)` / `Out`), and a per-look total. Each look gets a "Build cart for this look" handoff to workflow 4.

**Always disclose** that the try-on images are AI-generated previews, not photos of real garments on the customer.

### 4. Cart + checkout — "build me a cart" / "send me the checkout link"

1. Default path — **stateless cart link**:
   ```
   POST /mcp/buckmason/cart
   { "items": [{"slug_or_code":"daily-shirt-olive","size":"L","qty":1},
                {"slug_or_code":"tobacco-chino","size":"32x32","qty":1}],
     "coupon": "SPRING25" }
   ```
   Response includes `checkout_url` (a Shopify cart permalink) and `subtotal`. Hand the URL to the customer; they review and pay in their browser.

   **In-store pickup variant.** When the customer says "pickup", "I'll grab it", "have it ready at [store]", or names a Buck Mason store, build the cart with a pickup hint:
   ```
   POST /mcp/buckmason/cart
   { "items": [...],
     "pickup_location_slug": "abbot-kinney"   // OR "pickup_location_id": 2
   }
   ```
   The MCP server attaches `?attributes[Pickup-Location]=<name>` to the returned `checkout_url` so the pickup option pre-selects on Shopify's checkout. **Before building**, confirm every SKU is in stock at the named store via `/mcp/buckmason/stock/:sku` (filter by SKU + location). Behaviour by stock state:
   - All items in stock at the chosen store → build pickup cart, return `checkout_url` + a one-line "Ready for pickup at <store>" confirmation.
   - Customer named a store but it's out of stock → suggest the nearest in-stock pickup-enabled store and confirm before building.
   - Customer didn't name a store ("for pickup near me") → pick the nearest `pickup_enabled` store with all SKUs in stock; if none qualifies, fall back to ship-it with a one-line "no nearby store has all of these in stock; shipping default."
   - Mixed availability across the chosen store → don't auto-split. Tell the customer the gap and ask: pickup the in-stock items + ship the rest as two carts, or ship the whole order as one.
   - Pickup-disabled location → silently skip, pick the next-nearest.

   Don't substitute sizes for pickup convenience. If the customer's exact size is out at the chosen store but a different size is in, surface and ask — never substitute silently.
2. If the customer is logged in and wants to use a coupon or store credit before they hit Shopify, use `POST /api/update_cart` + `POST /api/add_coupon_or_customer_credit` (Pima-side cart) instead, then surface the resulting cart's checkout URL.

3. **Fully agent-driven checkout (MPP path).** When the customer wants the agent to handle the entire transaction — line items, shipping, payment, confirmation — without bouncing to a browser, use the **[Merchant Payments Protocol](https://mpp.dev)** endpoint at `POST https://pima.io/mcp/buckmason/checkout`. Required when the surface has no browser (voice agents, concierge flows, headless installations). The protocol uses HTTP 402 + `WWW-Authenticate: Payment` to challenge the agent for a **Stripe Shared Payment Token (SPT)**, which the agent obtains via **[stripe/link-cli](https://github.com/stripe/link-cli)** — the customer push-approves the spend in their Link wallet on their phone, and link-cli returns the SPT. The push-approval IS the consent. Always read the `total` back to the customer before kicking off `link-cli spend-request create`; always echo `acknowledged_total_cents` on the second POST to catch hallucinated totals. Coupons (`coupon: "..."`) and customer credits (`customer_credit_codes: [...]`) work as bearer codes — same model as POS. The full lifecycle, two-phase request shapes, guardrails (idempotency, total mismatch, card decline), coupon/credit envelope, and worked transcript are in **`references/mpp.md`** — read it before invoking the endpoint.

### 5. Order tracking + returns — "where's my order" / "I want to return this"

These are the most common post-purchase questions. They run on the same `/api/*` endpoints that power **orders.buckmason.com** (the Returns Management and Order Tracking portal).

1. **Identify the order.** Three paths, in this preference order — pick the lowest-friction one the user can satisfy:

   **a. Saved JWT** *(zero friction — no user action)*. If `profile.md → jwt` is set from a previous session, just resend it on `Authorization: <jwt>` (raw, no `Bearer` prefix). Skip to step 2.

   **b. Order code** *(lowest friction — recommended default for one-off lookups)*. Ask the user for their order number (e.g., `BM-12345`) — it's at the top of every order-confirmation email and on the printed receipt. Then pass `?order_code=<code>` on every `/api/*` call for the rest of this conversation. **No email read, no magic link, no JWT.** This is the right path for "where's my order?" and most return flows.

   **c. Email + magic link** *(high friction — only when the user wants account-wide access, e.g., to see all past orders for wardrobe seeding)*. This is a two-step flow:
     1. `POST /api/verify_order_or_email` with `{ value: "<email>", source: "returns" }` — Pima emails a magic link to the customer.
     2. The customer clicks the link in their inbox, OR the agent reads the email itself and extracts the token, OR the customer pastes the URL/token back into the chat. Then `POST /api/login_via_token` with `{ token: "<token>" }` returns a JWT. Save it to `profile.md → jwt` so the next session starts at path (a).

   **CRITICAL — magic-link capability check.** **Prefer "paste the link back" over agent-reads-mail.** The magic-link path requires the agent to either:
   - Have the customer paste the link / token back from their inbox after they receive the email (preferred — no extra capability granted to the agent), OR
   - Have a tool that reads the customer's email (e.g., a Gmail MCP server with read scope on the inbox of the email used for the purchase) — only with explicit operator authorization for that MCP server, and the agent restates that authorization in the same turn it reads the email, OR
   - Ask the customer to forward / paste back the link from their inbox (manual relay).

   **Before triggering `/api/verify_order_or_email`, confirm with the user how the link will be retrieved.** Surface the options in plain English: "I can either read the link from your inbox if you've connected an email tool, or you can paste it back to me after it arrives — which would you prefer?" Don't silently fire the email and then deadlock waiting for the token.

   **Always prefer (b) when possible.** "Do you have your order number?" is a one-second question and avoids both the email round-trip and the email-access permission. Only fall through to (c) when the user explicitly wants account-wide access (e.g., wardrobe seeding from full order history).
2. **Fetch status.** `GET /api/order_history?token=<jwt>` (or `?order_code=…`) returns the order with a `shipments[]` array — each shipment has `status` (`processing` / `shipped` / `delivered` / `delayed`), `tracking_code`, `tracking_url`, `shipped_at`, and `estimated_delivery_at`. Lead with the soonest estimated delivery + carrier link; mention any in-transit warning.
3. **Initiate a return.** If the user wants to return an item:
   - Pull the eligible items from the order (`order.items[].returnable: true` — anything not yet past Buck Mason's return window).
   - Surface the available `return_reasons` from `GET /api/return_reasons` (plain-text labels like "Doesn't fit", "Wrong color").
   - Ask which items + which reason, confirm, then `POST /api/customer_returns` with the chosen items + reason + the return shipping rate from `GET /api/shipping_rates`.
   - Hand back the return label URL from the response so the customer can print it.
4. **Surface the portal directly.** For complex multi-item returns or anything the agent can't fully handle, link the customer to **https://orders.buckmason.com/<order_code>** — the same flows as above, but in the customer's browser with full UI.

Don't fabricate tracking numbers or delivery dates from training data. If `/api/order_history` doesn't return what you need, say so and link the customer to orders.buckmason.com.

## Checkout safety

A shopping agent has full read/write access to a checkout flow. Treat any tool call that moves money as a destructive action that needs explicit confirmation in the same turn:

- **Default**: produce a Shopify cart link via `POST /mcp/buckmason/cart` for the customer to complete in their browser.
- **Agent-driven (MPP)**: only after the customer has explicitly opted into agent-driven payment, with the total restated in plain English in the same turn. The Stripe Shared Payment Token (minted by `stripe/link-cli` via the customer's push-approval in their Link app) IS the consent. Always echo `acknowledged_total_cents` on phase-2 to catch hallucinated totals.
- **Never** save a Stripe SPT, full card number, or CVV to any file. SPTs are one-time-use and short-lived; if you need to retry, mint a fresh one. The agent never asks the customer for raw card data — that flow does not exist in this skill.
- **Coupon codes**: apply only if the customer named the code or it's already saved as customer credit. Don't go hunting for coupons online — that's a different skill.

## Personalization signals

When choosing or recommending items, weight by (in this order):

1. **Hard constraints** — size, dress code (formality tier), season + climate (heat type from `references/seasons.md`).
2. **Reasoning filter** (`references/style-reasoning.md`) — fabric/weight must match climate (dry vs humid vs coastal mild vs altitude); silhouette must match formality tier; mix at least 60% classic + modern-staple.
3. **Profile prefs** — favorite colors, avoided fabrics/silhouettes, and especially `style_ethos` (drives the classic-vs-trend balance).
4. **Wardrobe gaps** — prefer items that fill a gap over duplicating something they own.
5. **Past orders** — if `account.orders` is loaded, infer fit history (returns suggest a size to avoid; repeat purchases suggest a winning style).
6. **"Sold with"** — Pima exposes `/api/products/:id/sold_with` and `/api/product_lines/:id/sold_with` for cross-sell, useful when filling out a look.

**Every recommendation must carry a rationale.** Output a one-sentence "why" per pick that names the climate fit, the formality fit, and the personal/classic angle. The default "this is in stock and on-trend" is not acceptable — see `references/style-reasoning.md` for the format and worked example.

## Error handling and degradation

- If Shopify Storefront is unreachable, fall back to Pima endpoints alone — the customer still gets catalog, locations, cart, and checkout, just without rich images and per-store availability. Tell them what's missing and why.
- If `/api/inventory` returns 403, don't have an inventory token — don't repeatedly retry. Switch to Shopify availability.
- If a SKU resolves to zero stock everywhere, offer `POST /api/restock_notifications` (`product_code`, `size_name`) and continue with alternatives.
- If image generation fails or is unavailable in the agent runtime, produce a **text-only lookbook** with product imagery laid out — never block the shopping flow on image generation.

## Output style

- Lead with the answer, not the methodology. "Yes, the Daily Shirt in olive, size L is in stock online and at Brentwood (4mi). Pickup today." beats a paragraph explaining how you checked.
- For lists of stores or items, use compact tables.
- Always include the product page URL alongside any recommendation so the customer can verify.
- Prices in USD with the dollar sign; convert Pima cents (`9720`) to dollars (`$97.20`) on display.

## Files in this skill

- `SKILL.md` — this file.
- `references/mcp-api.md` — **primary** API reference: Pima's `/mcp/*` endpoints.
- `docs/advanced/pima-api.md` — `/api/*` reference (login, account, **order history with shipment + tracking**, **return initiation**). Powers orders.buckmason.com (Returns Management and Order Tracking portal). Used by workflow #5. **Not used for purchasing** — purchases go through `POST /mcp/buckmason/cart` (browser) or `POST /mcp/buckmason/checkout` (MPP).
- `references/image-generation.md` — OpenAI image API prompt cookbook for try-on + lookbook.
- `references/seasons.md` — season + region + heat-type mapping for outfit logic.
- `references/style-reasoning.md` — the *why* engine: climate matrix, formality scale, classic-vs-trend filter, rationale format.
- `references/output-formats.md` — how to render the lookbook as `images` / `ppt` / `html`, plus quickest hosting options for the HTML format.
- `references/mpp.md` — Merchant Payments Protocol (mpp.dev) checkout: HTTP 402 challenge + Stripe Shared Payment Token via stripe/link-cli for fully agent-driven transactions when there's no browser. Two-phase request lifecycle, guardrails, and a worked transcript.
- `templates/profile.example.md`, `wardrobe.example.md`, `events.example.md` — copy these into the customer's workspace and fill in.
- `examples/stock-check.md`, `examples/lookbook.md` — concrete walkthroughs of the two main flows.
