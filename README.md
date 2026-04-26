# Buck Mason Stylist Skill

A personal-shopping skill for [Buck Mason](https://www.buckmason.com), built for Claude Code, Codex, ChatGPT custom GPTs, and any agent that loads `SKILL.md`–style skills. Talks to Buck Mason's public, path-tenanted MCP server (`pima.io/mcp/buckmason/*`) — no company key required.

## What it does

- **Stock check** — "do they have the [item] in my size, online and at the Abbot Kinney store?" — returns bucketed live counts (`In stock` / `Low stock (N left)` / `Out of stock`) per location.
- **Wardrobe gap analysis** — "what am I missing for a Sonoma wedding in May?" — diffs your owned items against a season + climate + dress-code-aware capsule recommendation, with a one-sentence "why" per pick.
- **AI try-on lookbooks** — generate editorial photos of you wearing the recommended outfits using OpenAI image-gen, with garment-level fidelity (color, fabric weight, silhouette) and identity preservation from your reference photos.
- **One-shot cart + checkout** — build a Shopify cart link or, if you're authenticated, charge a card on file (with explicit confirmation).

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
- `magick`, `wkhtmltopdf`, `python-pptx` — only needed for the editorial PDF/PPTX lookbook output

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
        outputs a PDF + clickable Shopify cart link]
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
| `templates/*.example.md` | Copy these into your workspace |
| `examples/*.md` | End-to-end walkthroughs |
| `PUBLISHING.md` | ClawHub distribution path |

## Install via ClawHub

```bash
clawhub install pima/buck-mason-stylist
```

(Once published — see `PUBLISHING.md` for status.)

## License

MIT. See `LICENSE`.

## Contributing

This skill is Buck Mason / Pima.io–specific by design. The MCP endpoints, brand voice, store footprint, and product taxonomy are all Buck Mason. Forks for other brands are welcome — replace the `/mcp/buckmason/...` paths with your own tenant slug, swap the references, and you're most of the way there.

Issues + PRs: <https://github.com/buckmason/buck-mason-stylist-skill> (TBD).
