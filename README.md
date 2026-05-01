# Buck Mason Stylist Skill

A personal-shopping skill for [Buck Mason](https://www.buckmason.com), built for Claude Code, Codex, ChatGPT custom GPTs, and any agent that loads `SKILL.md`–style skills. Talks to the pima.io MCP at `pima.io/mcp/buckmason/*`.

## What it does

- **Stock check** — "do they have the [item] in my size, online and at the Abbot Kinney store?" — returns bucketed live counts (`In stock` / `Low stock (N left)` / `Out of stock`) per location.
- **Wardrobe gap analysis** — "what am I missing for a Sonoma wedding in May?" — diffs your owned items against a season + climate + dress-code-aware capsule recommendation, with a one-sentence "why" per pick.
- **AI try-on lookbooks** — generate editorial photos of you wearing the recommended outfits using OpenAI image-gen, with garment-level fidelity (color, fabric weight, silhouette) and identity preservation from your reference photos.
- **One-shot cart + checkout** — default: stateless `POST /mcp/buckmason/cart` returns a Shopify permalink the customer pays in their browser. For fully agent-driven purchases (no browser), `POST /mcp/buckmason/checkout` speaks the [Merchant Payments Protocol](https://mpp.dev) — HTTP 402 + Stripe Shared Payment Token via [`stripe/link-cli`](https://github.com/stripe/link-cli), push-approved by the customer in the Link app. See `references/mpp.md`.

## Required setup

One environment variable:

```bash
export OPENAI_API_KEY=<your key>   # verified org for gpt-image-2; gpt-image-1 is a safe fallback
```

One profile file in your agent's workspace (copy from `templates/profile.example.md`):

```bash
cp templates/profile.example.md ~/agent-workspace/profile.md
$EDITOR ~/agent-workspace/profile.md   # fill in sizes, home zip, build, face, reference photos
```

That's it. No Buck Mason credentials. No Pima account.

Optional but useful:
- `wardrobe.md` — owned items (enables gap analysis)
- `events.md` — upcoming travel/events (enables event-aware suggestions)
- `magick`, `python-pptx`, `Pillow` — only needed for the editorial PPT/HTML lookbook output (see `references/output-formats.md`)
- [`stripe/link-cli`](https://github.com/stripe/link-cli) — only needed for the MPP fully-agent-driven checkout path

## Quick start

```text
You:  Stock check on the Daily Shirt in olive, in my size near 90291.
Skill: Online: 1,844 (in stock). Abbot Kinney: 36, Century City: 31. Pickup today.
       https://www.buckmason.com/products/olive-daily-shirt
```

```text
You:  Build me a 3-look capsule for a Sonoma wedding in May, smart-casual.
Skill: [pulls /mcp/buckmason/recommend, filters via style-reasoning matrix,
        diffs against your wardrobe, generates 3 editorial try-on images,
        outputs a 16:9 PPTX (or HTML) lookbook + a clickable Shopify cart
        link from POST /mcp/buckmason/cart, OR a fully-agent-driven MPP
        checkout if you've opted in]
```

See `examples/stock-check.md` and `examples/lookbook.md` for full walkthroughs.

## Files

| File | Purpose |
|---|---|
| `SKILL.md` | Main skill entry point — workflows, data sources, output style |
| `references/mcp-api.md` | Pima MCP endpoint contract |
| `docs/advanced/pima-api.md` | Advanced — legacy `/api/*` reference (login, account, checkout); not needed for v0.1.0 stylist flows |
| `references/image-generation.md` | OpenAI image-gen prompt cookbook + gpt-image-2 hint inventory |
| `references/seasons.md` | Season + region + heat-type mapping |
| `references/style-reasoning.md` | Climate matrix, formality scale, classic-vs-trend filter |
| `references/output-formats.md` | Lookbook output: `images` / `ppt` / `html` builders + quickest-host options |
| `references/mpp.md` | Merchant Payments Protocol checkout (mpp.dev + stripe/link-cli) — fully agent-driven transactions via HTTP 402 + Stripe Shared Payment Token |
| `templates/*.example.md` | Copy these into your workspace |
| `examples/*.md` | End-to-end walkthroughs |
| `PUBLISHING.md` | ClawHub distribution path |

## Install via ClawHub

Listing: <https://clawhub.ai/nickmerwin/buck-mason-stylist-skill>

```bash
clawhub install nickmerwin/buck-mason-stylist-skill
```

## License

MIT. See `LICENSE`.

## Contributing

This skill is Buck Mason / Pima.io–specific by design. The MCP endpoints, brand voice, store footprint, and product taxonomy are all Buck Mason. Forks for other brands are welcome — replace the `/mcp/buckmason/...` paths with your own tenant slug, swap the references, and you're most of the way there.

Source + issues: <https://github.com/pima-io/buck-mason-stylist-skill>
Listing: <https://clawhub.ai/nickmerwin/buck-mason-stylist-skill>
