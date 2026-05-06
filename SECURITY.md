# Security model

This document is the threat model + data-flow + guardrail reference for the
Buck Mason Stylist Skill. It exists so reviewers (humans and automated
scanners like ClawScan / VirusTotal Code Insight) can verify what this skill
does, what it can't do, and what the operator is on the hook for.

If you find a vulnerability, email **security@pima.io** — do not file a public
GitHub issue.

## TL;DR

- **No bundled binaries, no native modules, no install-time scripts.** The
  skill is markdown + JSON + Python sample code. Tools that get invoked are
  invoked through the *agent's* shell (`curl`, `jq`, `python3`,
  `python-pptx`, `Pillow`, optionally `magick` and `@stripe/link-cli`) — all
  under the operator's existing trust boundary.
- **No persistent server.** Everything runs as in-conversation tool calls
  from whatever agent loaded `SKILL.md`.
- **Default purchase path is a Shopify cart link** opened in the customer's
  own browser. Zero PCI exposure for the agent.
- **The agent-driven payment path (MPP)** never sees a card number; it only
  ever holds a one-time, short-lived **Stripe Shared Payment Token** minted
  by the customer push-approving the spend in their own Link wallet. The
  push-approval IS the consent. SPTs are never written to disk.
- **The OpenAI key is required only for the try-on lookbook workflow.** All
  other workflows (stock check, recommend, cart, MPP checkout, order
  tracking, returns) work with no OpenAI key at all.

## Data flow

| Source | Sink | Trigger | What goes |
|---|---|---|---|
| `profile.md` (sizes, build, face, photos) | OpenAI `/v1/images/edits` | Workflow #3 (try-on lookbook) | Reference photos + structured garment + setting prompt. Photos are sent only when the customer asks for a try-on. |
| `profile.md` (size, zip) | `pima.io/mcp/buckmason/*` | Workflows #1, #2, #4 | Just the size + zip — no photos, no contact info, no shipping address. |
| `profile.md` (shipping, name, email, phone) | `pima.io/mcp/buckmason/checkout` | Workflow #4 step 3 (MPP only, opt-in) | Buyer block sent to Pima for the payment intent. Not sent on cart-link path. |
| `profile.md` (email) | Customer's own inbox via Pima | Workflow #5c (magic-link, opt-in only) | Email is delivered by Pima to the customer; the agent never sees it unless an explicit email-MCP is authorized in the same turn. |
| Shopify cart permalink | Customer's browser | Workflow #4 default | URL only; the customer takes it from there. |
| `wardrobe.md`, `events.md` | Local filesystem only | All workflows that read them | Never sent to any external service. |
| `html-cart` selection block (slug + size + qty + lookbook_id) | `~/.buck-mason-stylist/wishlist.jsonl` (local filesystem) | Workflow #4 path B on handoff paste-back and on successful MPP order | Append-only JSONL. Contains slug, size, qty, `lookbook_id`, `price_cents_at_pick`, and (after settlement) `order_id` + `purchased_at`. No card data, no shipping address, no email, no full name. Lives outside the workspace so it persists across agent sessions on the same machine — declared in `clawhub.json#permissions.filesystem`. |

Nothing in this skill writes to anywhere outside the operator's workspace
or the wishlist path declared in `clawhub.json#permissions.filesystem`,
and never to any host outside the four listed in
`clawhub.json#permissions.network`.

## Threat model

### What the skill DOES NOT do (deliberately)

- It does **not** ask for, store, or transmit raw card numbers, CVVs,
  routing numbers, or bank credentials. Stripe SPTs are the only payment
  artifact the agent ever holds.
- It does **not** read the customer's email automatically. The magic-link
  flow (workflow #5c) is opt-in; default is the guest `?order_code=` path.
  When email is read, it requires an explicitly authorized email MCP and
  the agent restates the authorization in the same turn.
- It does **not** auto-checkout. Even on the MPP path, the agent must read
  back items + total + shipping + return policy in plain English in the same
  turn and wait for an unambiguous "yes, go ahead" before invoking
  `link-cli spend-request create --request-approval`.
- It does **not** install or fetch code at runtime. Optional dependencies
  (`@stripe/link-cli`, `magick`) are operator-installed.
- It does **not** include or vendor third-party CLIs. The skill references
  `@stripe/link-cli` by its npm scope (verified Stripe publisher) and links
  to the source repo. If you don't want it, leave it uninstalled — the
  default cart-link path will still work.
- It does **not** keep a long-lived server-side session. There's no
  database, no key-value store, no queue. Each tool call is a stateless
  HTTP request to `pima.io` or `api.openai.com`.

### What an operator opts into

| Capability | Default | Opt-in |
|---|---|---|
| Stock check, recommend, cart link | ✅ on | — |
| Order tracking via guest order-code | ✅ on | — |
| AI try-on (sends photos to OpenAI) | ❌ off (requires `OPENAI_API_KEY` and an explicit user ask) | per-conversation |
| MPP fully-agent-driven checkout | ❌ off (requires `@stripe/link-cli` and an explicit user opt-in to agent-driven payment) | per-purchase |
| Email magic-link account linking | ❌ off | per-conversation, with retrieval method confirmed before sending the email |

If the operator wires the skill into an agent without `OPENAI_API_KEY` and
without `@stripe/link-cli`, all the high-risk capabilities are unreachable
by construction.

### Risks the skill cannot mitigate

These are the operator's responsibility:

- **Workspace integrity.** `profile.md` lives in the agent's workspace. If
  the workspace is shared (a shared box, a CI runner, a multi-tenant
  filesystem) the operator must restrict it. Recommendations:
  - Keep `profile.md` minimal — the skill only needs sizes + zip for stock
    checks. Shipping, photos, full address are required only for the
    workflows that explicitly need them.
  - Don't check `profile.md` into git. The skill's `templates/profile.example.md`
    is committed; the filled-in version should not be.
- **Agent host trust.** The skill assumes the agent host can keep
  `OPENAI_API_KEY` out of public conversation logs and out of LLM context
  it doesn't need. The skill itself never echoes the key.
- **Email MCP scope.** If the operator wires a Gmail/IMAP MCP with broad
  read scope solely for the magic-link flow, that's a much larger blast
  radius than the magic-link workflow itself. Prefer the customer pasting
  the link back, or scope the MCP to just the inbox tied to the Buck Mason
  email.
- **Network-level interception.** The skill talks to `pima.io` and
  `api.openai.com` over TLS. The operator is responsible for the host's
  CA store.

## Permission breadth (what to expect on install)

Network egress (declared in `clawhub.json#permissions.network`):
- `pima.io` — MCP catalog, stock, locations, cart, MPP checkout
- `www.buckmason.com` — public storefront aliases for the same MCP
- `cdn.shopify.com` — product imagery for lookbook generation
- `api.openai.com` — image generation (`gpt-image-2`), try-on workflow only

Filesystem (declared in `clawhub.json#permissions.filesystem`):
- `<workspace>/profile.md` — read
- `<workspace>/wardrobe.md` — read (optional)
- `<workspace>/events.md` — read (optional)
- `<workspace>/lookbook/` — write (generated PNG/PPTX/HTML output, only on
  workflows that produce them)

That's the entire surface. Nothing else is required.

## Reporting

- **Vulnerabilities**: security@pima.io
- **Spec questions**: open an issue at
  https://github.com/pima-io/buck-mason-stylist-skill
- **General docs**: see `SKILL.md`, `references/mcp-api.md`, `references/mpp.md`,
  `references/image-generation.md`

## Versioning

This security model applies to the current major version (0.x). Material
changes — new capabilities, new permissions, new outbound network hosts —
will trigger a minor version bump and a `CHANGELOG.md` entry calling out
the security delta.
