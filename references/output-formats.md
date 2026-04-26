# Lookbook output formats

Three supported outputs from the lookbook workflow (`SKILL.md` workflow 3, step 4):

| Format | Build time | Best for |
|---|---|---|
| `images` (PNG only) | ~0s after generation | Quick iteration, "just show me" |
| `ppt` (`.pptx`) | ~2s | Sharing for review (stylist, SO, yourself) |
| `html` (`.html`) | ~1s | Public preview link, email body, browser sharing |

Every format MUST include, per piece:
1. Product name
2. Price (USD with `$`)
3. Clickable `buckmason.com/products/<slug>` link
4. In-your-size stock per location, bucketed: `In stock` / `Low (N)` / `Out of stock`
5. Per-look total at the bottom of each look

Identity disclosure ("AI-generated try-on preview, not a real photo of you in the garment") goes on the cover or the footer of the deck/page.

---

## 1. `images` — raw PNGs

Just the files written by the OpenAI image-edit calls. No assembly. Output to `lookbook/<date>-<event>-look-N.png`. List the file paths back to the customer with the per-piece info as plain markdown:

```
Look 01 — Mediterranean Evening
   lookbook/2026-04-26-sonoma-look-1.png

   • Brown / Natural Gun Club Graduate Jacket — $698 — In stock
     https://www.buckmason.com/products/brown-natural-gun-club-graduate-jacket
   • Faded Indigo Como Cashmere Polo — $168 — In stock
     https://www.buckmason.com/products/faded-indigo-como-cashmere-polo
   • Chocolate Irish Linen Hollywood Pleated Trouser — $298 — Low (1)
     https://www.buckmason.com/products/chocolate-irish-linen-hollywood-pleated-trouser

   Look 01 total: $1,164
```

---

## 2. `ppt` — `.pptx` slide deck

Build with `python-pptx`. 16:9 widescreen (`13.333" × 7.5"`). One slide per look + one cover slide.

### Required Python deps
```
python-pptx
Pillow
```

### Slide layout
- **Cover slide**: brand eyebrow, title (e.g., "Three Anchors"), one-line subtitle, list of featured anchor pieces with names + prices + clickable links, "Stores near 90291" block.
- **Per-look slide**: `LOOK 01` eyebrow, title (e.g., "Mediterranean Evening"), one-sentence occasion note, generated look image on the left (5" tall), per-piece rows on the right (1.4" thumbnail + name + price + clickable link + stock line), per-look total at the bottom.

### Clickable hyperlinks — non-negotiable
Every URL on the deck MUST be a real hyperlink. In `python-pptx`:

```python
run = paragraph.add_run()
run.text = "buckmason.com/products/..."
run.hyperlink.address = "https://www.buckmason.com/products/..."
```

PowerPoint and Keynote do NOT auto-detect plain URL text — without `run.hyperlink.address` the link is dead.

### Stock-line format
```
Size L — Online: In stock  ·  Abbot Kinney: Low (5)  ·  Century City: Out  ·  Bloomies CC: Low (3)
```

The bucket thresholds and labels come from the same logic as `/mcp/buckmason/stock/:sku`:
- `0` → `Out of stock` (or just `Out` for compact display)
- `1–9` → `Low (N)`
- `10+` → `In stock` (no exact count surfaced)

### Reference implementation
A working `python-pptx` builder is shipped in the test-output / dev fixtures of this repo's history — search for `build-outfit*-deck.py`. Reuse its `cover_slide()` and `look_slide()` functions; only the data inputs change between lookbooks.

---

## 3. `html` — single self-contained `.html`

Build with a string template — no framework needed. Single file, ~30 KB before image embedding, ~3–8 MB with images embedded as base64.

### Why self-contained
- Works offline (no broken images when the customer airdrops it to themselves)
- Single attachment in email
- Trivial to host (any static host accepts it)
- Survives moving between devices without breaking image paths

### Layout
Vertical scroll: cover section → one section per look. Same content as the PPT but in a single document. Mobile-responsive: the per-piece grid collapses to a single column under 700px.

### Skeleton

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Buck Mason Lookbook</title>
  <style>
    /* Embed all CSS inline — no external stylesheets */
    body { font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; color: #1a1a1a; background: #faf8f4; margin: 0; }
    .page { max-width: 1100px; margin: 0 auto; padding: 48px 32px; }
    .cover h1 { font-family: Georgia, serif; font-weight: 400; font-size: 48px; margin: 0 0 8px; }
    .look { display: grid; grid-template-columns: 1fr 1fr; gap: 32px; padding: 48px 0; border-top: 1px solid #e5e5e5; }
    @media (max-width: 700px) { .look { grid-template-columns: 1fr; } }
    .look img.hero { width: 100%; border: 1px solid #eee; }
    .piece { display: flex; gap: 12px; padding: 12px 0; border-top: 1px solid #eee; }
    .piece img { width: 80px; height: 100px; object-fit: contain; background: #fafafa; border: 1px solid #efefef; }
    .piece .name { font-weight: 600; }
    .piece a { color: #666; font-size: 12px; word-break: break-all; }
    .stock { font-size: 11px; color: #666; margin-top: 4px; }
    .total { font-weight: 700; padding-top: 12px; border-top: 2px solid #1a1a1a; margin-top: 12px; }
    .footer { text-align: center; font-size: 11px; color: #999; padding: 24px; }
  </style>
</head>
<body>
  <section class="page cover">
    <div style="font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:#666;">Buck Mason · Spring 2026</div>
    <h1>Three Looks for Sonoma</h1>
    <p style="color:#666;">An editorial styling for a May wedding weekend.</p>
  </section>

  <section class="page look">
    <div><img class="hero" src="data:image/png;base64,…" alt="Look 01"></div>
    <div>
      <div style="font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:#888;">Look 01</div>
      <h2 style="font-family:Georgia,serif;font-weight:400;">Mediterranean Evening</h2>

      <div class="piece">
        <img src="data:image/jpeg;base64,…">
        <div>
          <div class="name">Brown / Natural Gun Club Graduate Jacket</div>
          <div>$698</div>
          <a href="https://www.buckmason.com/products/brown-natural-gun-club-graduate-jacket">buckmason.com/products/brown-natural-gun-club-graduate-jacket</a>
          <div class="stock">Size L — Online: In stock · Abbot Kinney: Low (5) · Century City: Out · Bloomies CC: Out</div>
        </div>
      </div>
      <!-- More pieces -->

      <div class="total">Look 01 total · $1,164</div>
    </div>
  </section>
  <!-- More looks -->

  <div class="footer">AI-generated try-on preview · Buck Mason / Pima.io</div>
</body>
</html>
```

### Image embedding (base64)

```bash
# bash one-liner per image
b64=$(base64 -i lookbook/2026-04-26-look-1.png)
# then string-substitute into the template: src="data:image/png;base64,$b64"
```

Or in Python:
```python
import base64, mimetypes, pathlib
def embed(path):
    mime, _ = mimetypes.guess_type(str(path))
    b64 = base64.b64encode(pathlib.Path(path).read_bytes()).decode()
    return f"data:{mime};base64,{b64}"
```

### File-size sanity check
- 3 looks × (1 hero @ 2 MB + 3 thumbnails @ 200 KB) = ~7.8 MB raw → ~10.4 MB base64-encoded.
- If size matters (email attachment, mobile), pre-resize the hero PNGs to 1024px wide JPEG with `magick hero.png -resize 1024x -quality 85 hero.jpg` before embedding — drops to ~3 MB total.

---

## Hosting the HTML lookbook online — quickest options

Once you have `lookbook.html` on disk, ranked by friction (lowest first):

### a. **0x0.st** — fastest, no auth (recommended default)
```bash
curl -F "file=@lookbook.html" https://0x0.st
# → https://0x0.st/aBcD.html
```
- Zero sign-up, zero CLI install
- File persists ~30 days minimum (longer for smaller files)
- HTML renders in-browser at the returned URL
- 256 MB max
- Caveat: anonymous, public — anyone with the URL can view

### b. **GitHub Gist (anonymous public)** — persistent, requires `gh`
```bash
gh gist create lookbook.html --public --desc "Buck Mason lookbook"
# → https://gist.github.com/<user>/<sha>
# Then click the "Raw" button to get a render-as-HTML URL via htmlpreview.github.io:
# https://htmlpreview.github.io/?https://gist.githubusercontent.com/<user>/<sha>/raw/lookbook.html
```
- Persistent, no expiry
- Versioned (you can update later)
- Requires `gh auth login` once
- Caveat: indexed by Google eventually

### c. **Surge.sh** — persistent custom subdomain
```bash
npx surge lookbook.html buckmason-may-wedding.surge.sh
# → https://buckmason-may-wedding.surge.sh
```
- Custom subdomain, free
- Persistent
- One-time email signup
- Caveat: indefinite retention but no version history

### d. **Cloudflare Pages direct upload** — production-grade, persistent, custom domain capable
```bash
mkdir _cf && cp lookbook.html _cf/index.html
npx wrangler pages deploy _cf --project-name buckmason-lookbook
# → https://<deployment>.buckmason-lookbook.pages.dev
```
- Permanent, fast (Cloudflare CDN)
- Custom domain optional
- Requires Cloudflare account + `wrangler login`

### e. **Pima preview endpoint** (future / on-brand)
The cleanest on-brand option is to POST the HTML to a future `POST /mcp/buckmason/preview` endpoint that returns a `https://www.buckmason.com/p/<short-id>` URL. This is **not yet implemented** — flag it as a follow-up if a customer asks for branded preview links.

### Quick decision tree
- "Just show my friend right now" → **0x0.st**
- "I want to keep it forever" → **Surge** or **Gist**
- "Send to a Buck Mason customer" → **Cloudflare Pages** with a custom subdomain (e.g., `nick-spring-2026.lookbook.buckmason.com`)
- "On-brand permalink" → wait for **Pima preview endpoint**

After hosting, hand the URL back to the customer + offer a one-line "Open it" + a "Build cart for Look 01 — $1,164" button (workflow 4).

---

## Common build pitfalls

1. **Plain-text URLs in PPT** — Keynote/PowerPoint do not auto-link. Wire `run.hyperlink.address` at generation time. Same applies to PDF if you ever add that format.
2. **Forgetting in-your-size stock filter** — generic "available online" is wrong; the customer wants per-size. Compute by SKU IDs, not Product IDs.
3. **HTML without base64 embed** — `file://` references break the moment the file moves. Always embed for portability.
4. **Hero PNG too large** — 2 MB × 3 looks = 6 MB of inline data → email rejected by some servers. Pre-resize to 1024px JPEG.
5. **Setting drift dropping anchor pieces** — gpt-image-2 sometimes drops outer layers. See `references/image-generation.md` "gpt-image-2 hint inventory" for the JACKET LOCK pattern.
