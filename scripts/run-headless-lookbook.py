#!/usr/bin/env python3
"""End-to-end headless lookbook orchestrator.

Composes the deterministic chain:
  score (event-driven only) → discover candidates → curate
  → build (Editorial tier by default) → deploy (gated on _auto)
  → validate → write summary

Spec: references/headless-mode.md § "The end-to-end orchestrator".

Modes
-----
  --weekly                 Recurring weekly newsletter mode. Uses
                           scripts/discover-weekly-candidates.py to surface
                           recently-live + previously-unproposed products.

  --event <path>           Event-driven mode. Reads the event JSON, scores
                           it via scripts/score-calendar-event.py, and
                           proceeds only if action ∈ {editorial, premium}.
                           skip / hard-veto exits with summary, no lookbook.
                           soft (score=6) emits a one-line "ready when you
                           are" summary, no generation.

Common args
-----------
  --profile <path>         profile.md (or YAML/JSON sibling). Reads sizes,
                           gender, ethos, link_payment_method,
                           preferred_lookbook_host*, weekly_lookbook_*,
                           lookbook_project_prefix, notify_url.

  --runs-dir <path>        Default ~/.buck-mason-stylist/runs/
  --wishlist <path>        Default ~/.buck-mason-stylist/wishlist.jsonl
  --max-pieces N           Default 6; cap on candidates picked
  --tier <auto|editorial|premium>
                           Default `auto` — picks Premium if event scores
                           ≥9 AND OPENAI_API_KEY present AND ≥2 reference
                           photos exist. Else Editorial. `--tier editorial`
                           or `--tier premium` forces.

Premium tier note
-----------------
Premium tier requires gpt-image-2 calls (~$0.40/run) which need a
specifically-crafted prompt template (see references/image-generation.md).
This orchestrator does NOT invoke OpenAI directly — it stops at the build
step with the run config + picks ready, and the agent generates the look
images separately, drops them into runs/<id>/looks/, then re-runs the
orchestrator with --resume-build to pick up at the build stage.
"""
import argparse, json, os, pathlib, re, subprocess, sys, time, urllib.parse

ROOT = pathlib.Path(__file__).resolve().parent
SKILL_ROOT = ROOT.parent

# ── CLI ─────────────────────────────────────────────────────────────────────
ap = argparse.ArgumentParser(description="Headless lookbook orchestrator.")
mode = ap.add_mutually_exclusive_group(required=True)
mode.add_argument("--weekly", action="store_true", help="Weekly newsletter mode.")
mode.add_argument("--event",  type=pathlib.Path, help="Event JSON (reads via scripts/score-calendar-event.py).")
ap.add_argument("--profile",     type=pathlib.Path, required=True)
ap.add_argument("--runs-dir",    type=pathlib.Path, default=pathlib.Path.home() / ".buck-mason-stylist/runs")
ap.add_argument("--wishlist",    type=pathlib.Path, default=pathlib.Path.home() / ".buck-mason-stylist/wishlist.jsonl")
ap.add_argument("--max-pieces",  type=int, default=6)
ap.add_argument("--tier",        choices=["auto", "editorial", "premium"], default="auto")
ap.add_argument("--resume-build",action="store_true", help="Skip discover/curate; re-build from existing run dir. Use after dropping look images for Premium tier.")
ap.add_argument("--lookbook-id", type=str, help="Override the auto-derived lookbook_id.")
args = ap.parse_args()

args.runs_dir.mkdir(parents=True, exist_ok=True)
args.wishlist.parent.mkdir(parents=True, exist_ok=True)

# ── Profile loader (small, doesn't fight the schema) ───────────────────────
def parse_profile(path: pathlib.Path) -> dict:
    """Pull the YAML-ish key:value lines from profile.md. Cheap and good
    enough for the headless orchestrator — full schema lives in
    templates/profile.schema.json."""
    if not path.exists():
        return {}
    text = path.read_text()
    out = {}
    # Capture top-level "- key: value" or "key: value" lines
    for line in text.splitlines():
        m = re.match(r'^\s*-?\s*([a-z][a-z0-9_]*)\s*:\s*(.+?)\s*(?:#.*)?$', line)
        if m:
            k, v = m.group(1), m.group(2).strip()
            v = v.strip('"').strip("'")
            if v.lower() in ("true", "false"):
                v = (v.lower() == "true")
            elif v.lower() in ("null", "none", ""):
                v = None
            out.setdefault(k, v)
    # Reference photo paths
    photos = []
    for m in re.finditer(r'^\s*-\s*path:\s*(.+?)\s*(?:#.*)?$', text, re.M):
        photos.append(m.group(1).strip().strip('"').strip("'"))
    if photos:
        out["reference_photos"] = photos
    # sizes block
    sizes = {}
    in_sizes = False
    for line in text.splitlines():
        if re.match(r'^\s*##\s*Sizes', line, re.I):
            in_sizes = True; continue
        if in_sizes and re.match(r'^\s*##', line):
            in_sizes = False
        if in_sizes:
            m = re.match(r'^\s*-?\s*(shirt|tee|pant|short|jacket|sport_coat|shoe|belt|jean)\s*:\s*([^\s#]+)', line)
            if m:
                sizes[m.group(1)] = m.group(2)
    if sizes:
        out["sizes"] = sizes
    return out

profile = parse_profile(args.profile)
gender               = profile.get("gender", "u")
sizes                = profile.get("sizes", {})
ethos                = profile.get("style_ethos", "")
favorites            = profile.get("favorites") or ""
auto_publish         = bool(profile.get("preferred_lookbook_host_auto", False))
project_prefix       = profile.get("lookbook_project_prefix") or "buckmason"
home_zip             = profile.get("home_zip", "")
reference_photos     = profile.get("reference_photos", [])
openai_key_set       = bool(os.environ.get("OPENAI_API_KEY"))

# ── Summary writer ─────────────────────────────────────────────────────────
def write_summary(run_dir: pathlib.Path, body: str):
    """Per references/headless-mode.md § run summary format."""
    (run_dir / "summary.md").write_text(body)
    # Single-line URL/blocker on stdout for headless callers
    first = body.strip().splitlines()[0] if body.strip() else ""
    print(first)

def fail(run_dir: pathlib.Path, stage: str, reason: str, tier: str = "—"):
    body = (
        f"# Lookbook run — {time.strftime('%Y-%m-%d')}\n"
        f"\n"
        f"❌ BLOCKER: {reason}\n"
        f"Tier attempted: {tier}\n"
        f"Stage failed: {stage}\n"
        f"\n"
        f"Detail\n"
        f"{reason}\n"
    )
    write_summary(run_dir, body)
    sys.exit(2)

# ── Mode: --event ──────────────────────────────────────────────────────────
event_action = None
event_score  = None
event_label  = None
if args.event:
    if not args.event.exists():
        print(f"error: event file not found: {args.event}", file=sys.stderr)
        sys.exit(2)
    score_p = subprocess.run(
        ["python3", str(ROOT / "score-calendar-event.py")],
        input=args.event.read_text(),
        capture_output=True, text=True,
    )
    if score_p.returncode != 0:
        print(f"error: scorer exited non-zero: {score_p.stderr}", file=sys.stderr)
        sys.exit(2)
    score_obj = json.loads(score_p.stdout)
    event_score  = score_obj.get("score")
    event_action = score_obj.get("action")
    event_label  = score_obj.get("reason")
    if event_action == "skip":
        # Hard veto or below threshold — silent skip; no run dir needed.
        print(f"score={event_score} action=skip reason={event_label} — no lookbook generated.")
        sys.exit(0)
    if event_action == "soft":
        # One-line surface; no generation in headless mode.
        print(f"score={event_score} action=soft — surface to customer next interactive turn.")
        sys.exit(0)

# ── Lookbook id + run dir ──────────────────────────────────────────────────
today = time.strftime("%Y-%m-%d")
if args.lookbook_id:
    lookbook_id = args.lookbook_id
elif args.weekly:
    iso_year, iso_week, _ = time.gmtime().tm_year, time.strftime("%V"), 0
    lookbook_id = f"{time.strftime('%Y')}-weekly-{time.strftime('%V')}"
else:
    # Event-driven — derive from event title
    ev_data = json.loads(args.event.read_text())
    slug = re.sub(r'[^a-z0-9]+', '-', (ev_data.get("title") or "event").lower()).strip('-')[:32] or "event"
    lookbook_id = f"{today}-{slug}"

run_dir = args.runs_dir / lookbook_id
(run_dir / "looks").mkdir(parents=True, exist_ok=True)
(run_dir / "deploy").mkdir(parents=True, exist_ok=True)

# ── Curate (skipped on --resume-build) ─────────────────────────────────────
picks_path  = run_dir / "picks.json"
config_path = run_dir / "config.json"
candidates_path = run_dir / "candidates.json"

def derive_tier() -> str:
    if args.tier != "auto":
        return args.tier
    if event_score and event_score >= 9 and openai_key_set and len(reference_photos) >= 2:
        return "premium"
    return "editorial"

if not args.resume_build:
    # ── Discover candidates ────────────────────────────────────────────────
    if args.weekly:
        sizes_arg = json.dumps({k: str(v) for k, v in sizes.items() if v})
        disc_p = subprocess.run([
            "python3", str(ROOT / "discover-weekly-candidates.py"),
            "--gender", str(gender),
            "--since-days", "30",
            "--wishlist", str(args.wishlist),
            "--sizes", sizes_arg,
            "--max", str(max(args.max_pieces * 3, 18)),
        ], capture_output=True, text=True)
        if disc_p.returncode != 0:
            fail(run_dir, "discover", f"discover-weekly-candidates failed: {disc_p.stderr.strip()[:200]}")
        cand = json.loads(disc_p.stdout)
        candidates_path.write_text(json.dumps(cand, indent=2))
    else:
        # Event-driven: use the event's hint to query MCP (light-weight)
        # The agent typically pre-curates and writes picks.json directly,
        # then re-runs with --resume-build. If picks.json is missing here,
        # we fall back to the same discover script with the event's gender.
        if not picks_path.exists():
            sizes_arg = json.dumps({k: str(v) for k, v in sizes.items() if v})
            disc_p = subprocess.run([
                "python3", str(ROOT / "discover-weekly-candidates.py"),
                "--gender", str(gender),
                "--since-days", "60",
                "--wishlist", str(args.wishlist),
                "--sizes", sizes_arg,
                "--max", str(max(args.max_pieces * 3, 18)),
            ], capture_output=True, text=True)
            if disc_p.returncode != 0:
                fail(run_dir, "discover", f"discover-weekly-candidates failed: {disc_p.stderr.strip()[:200]}")
            cand = json.loads(disc_p.stdout)
            candidates_path.write_text(json.dumps(cand, indent=2))

    # ── Curate (taste-light v1: take top N, group into 1–2 looks) ─────────
    if not picks_path.exists():
        cand = json.loads(candidates_path.read_text()) if candidates_path.exists() else {"candidates": []}
        chosen = cand.get("candidates", [])[: args.max_pieces]
        if not chosen:
            fail(run_dir, "curate", f"discover returned 0 candidates — nothing new to surface this run", tier="—")
        # Group: half the picks into look1, half into look2 (or all into look1
        # if fewer than 4)
        half = max(1, len(chosen) // 2)
        for i, p in enumerate(chosen):
            p["look"] = "look1" if i < half else "look2"
            p["picked_size"] = p.get("size") or sizes.get("shirt") or "L"
        picks_path.write_text(json.dumps(chosen, indent=2))

    # ── Config ────────────────────────────────────────────────────────────
    if not config_path.exists():
        if args.weekly:
            title = f"This Week from Buck Mason — {today}"
            subtitle = f"What's new on buckmason.com plus pieces I haven't pitched you before, in your size."
        else:
            ev = json.loads(args.event.read_text())
            ev_title = ev.get("title") or "Event"
            title = f"For {ev_title}"
            subtitle = ev.get("description") or "An outfit suggestion for this event."
        looks_meta = []
        for look_id in ("look1", "look2"):
            if any(p["look"] == look_id for p in json.loads(picks_path.read_text())):
                idx = 1 if look_id == "look1" else 2
                looks_meta.append({
                    "id": look_id,
                    "eyebrow": f"Look {idx:02d}",
                    "title": f"Look {idx}",
                    "note": "",
                })
        project = f"{project_prefix}-{lookbook_id}"
        page_url = f"https://{project}.pages.dev/"
        config_path.write_text(json.dumps({
            "lookbook_id":    lookbook_id,
            "lookbook_title": title,
            "lookbook_date":  today,
            "subtitle":       subtitle,
            "page_url":       page_url,
            "looks":          looks_meta,
        }, indent=2))

# ── Build ──────────────────────────────────────────────────────────────────
tier = derive_tier()
deploy_dir = run_dir / "deploy"

build_args = [
    "python3", str(ROOT / "build-html-lookbook.py"),
    "--config", str(config_path),
    "--picks",  str(picks_path),
    "--out",    str(deploy_dir),
]
if tier == "premium":
    looks_dir = run_dir / "looks"
    # Verify we actually have the per-look images + the marker
    pngs = sorted(looks_dir.glob("look*.png"))
    if not pngs:
        # Premium path needs the agent to drop look images first.
        # Use an unmistakable machine-readable marker on stdout + a structured
        # heading in the summary so an agent (or another script) can branch
        # on the run state without parsing prose.
        body = (
            f"READY_FOR_PREMIUM_IMAGE_STEP\n"
            f"\n"
            f"# Lookbook run — {today}\n"
            f"\n"
            f"Status: READY_FOR_PREMIUM_IMAGE_STEP\n"
            f"Tier:   premium\n"
            f"Stage:  awaiting-look-images\n"
            f"\n"
            f"Premium tier needs gpt-image-2 outputs at:\n"
            f"  {looks_dir}/look1.png\n"
            f"  {looks_dir}/look2.png\n"
            f"  {looks_dir}/.lookbook_id  (must contain: {lookbook_id})\n"
            f"\n"
            f"Next steps (pick ONE):\n"
            f"  (a) Generate the try-on images per references/image-generation.md,\n"
            f"      drop them at the paths above, write the .lookbook_id marker,\n"
            f"      then re-run this orchestrator with --resume-build.\n"
            f"  (b) Fall back to Editorial tier (no AI try-on) with --tier editorial.\n"
            f"\n"
            f"Run dir: {run_dir}\n"
        )
        write_summary(run_dir, body)
        sys.exit(0)
    build_args += ["--look-images", str(looks_dir)]
else:
    build_args += ["--no-tryon"]

build_p = subprocess.run(build_args, capture_output=True, text=True)
if build_p.returncode != 0:
    fail(run_dir, "build", f"build-html-lookbook.py exit {build_p.returncode}: {build_p.stderr.strip()[:400]}", tier=tier)

# ── Validate (local) ───────────────────────────────────────────────────────
validate_p = subprocess.run(
    ["python3", str(ROOT / "validate-lookbook.py"), "--dir", str(deploy_dir)],
    capture_output=True, text=True,
)
if validate_p.returncode != 0:
    fail(run_dir, "validate-local", f"local validation failed: {validate_p.stdout.strip()[-400:]}", tier=tier)

# ── Deploy (gated on profile) ─────────────────────────────────────────────
project_name = f"{project_prefix}-{lookbook_id}"
page_url = f"https://{project_name}.pages.dev/"

if not auto_publish:
    body = (
        f"# {json.loads(config_path.read_text())['lookbook_title']} — {today}\n"
        f"\n"
        f"📦 READY TO DEPLOY\n"
        f"Tier: {tier.title()}\n"
        f"Looks: {len(json.loads(config_path.read_text())['looks'])}\n"
        f"Pieces: {len(json.loads(picks_path.read_text()))}\n"
        f"\n"
        f"Run dir: {run_dir}\n"
        f"\n"
        f"To publish, set profile.md → preferred_lookbook_host_auto: true\n"
        f"or run interactively:\n"
        f"  bash scripts/deploy-lookbook.sh {deploy_dir} {project_name} --no-overwrite\n"
    )
    write_summary(run_dir, body)
    sys.exit(0)

deploy_p = subprocess.run(
    ["bash", str(ROOT / "deploy-lookbook.sh"), str(deploy_dir), project_name, "--auto", "--no-overwrite"],
    capture_output=True, text=True,
)
if deploy_p.returncode != 0:
    fail(run_dir, "deploy", f"deploy-lookbook.sh exit {deploy_p.returncode}: {deploy_p.stderr.strip()[-400:]}", tier=tier)

# ── Validate (deployed) ───────────────────────────────────────────────────
validate_d = subprocess.run(
    ["python3", str(ROOT / "validate-lookbook.py"), "--url", page_url],
    capture_output=True, text=True,
)
if validate_d.returncode != 0:
    fail(run_dir, "validate-deployed", f"deployed validation failed: {validate_d.stdout.strip()[-400:]}", tier=tier)

# ── Wishlist append ───────────────────────────────────────────────────────
proposed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
with args.wishlist.open("a") as f:
    for p in json.loads(picks_path.read_text()):
        f.write(json.dumps({
            "sku":           p.get("sku"),
            "name":          p.get("name"),
            "size":          p.get("picked_size") or p.get("size"),
            "qty":           1,
            "lookbook_id":   lookbook_id,
            "lookbook_url":  page_url,
            "proposed_at":   proposed_at,
            "purchased_at":  None,
            "order_id":      None,
        }) + "\n")

# ── Success summary ───────────────────────────────────────────────────────
cfg  = json.loads(config_path.read_text())
picks = json.loads(picks_path.read_text())
in_stock_count = sum(
    1 for p in picks
    if isinstance(p.get("in_stock_online"), dict) and p["in_stock_online"].get("in_stock")
)
subtotal = sum(p.get("price_cents", 0) for p in picks) / 100

body = (
    f"# {cfg['lookbook_title']}\n"
    f"\n"
    f"✅ Deployed: {page_url}\n"
    f"Tier: {tier.title()}\n"
    f"Looks: {len(cfg['looks'])}\n"
    f"Pieces: {len(picks)} · in stock {in_stock_count}/{len(picks)}\n"
    f"Subtotal at pick: ${subtotal:.2f}\n"
    f"\n"
    f"Notes\n"
    + (f"- Event score: {event_score} ({event_label})\n" if event_score is not None else "")
    + f"- Run dir: {run_dir}\n"
    f"\n"
    f"Verify: https://www.opengraph.xyz/url/{urllib.parse.quote(page_url, safe='')}\n"
)
write_summary(run_dir, body)
