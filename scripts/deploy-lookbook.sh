#!/usr/bin/env bash
# Deploy a built lookbook directory to Cloudflare Pages.
#
# Usage:
#   scripts/deploy-lookbook.sh <deploy-dir> <project-name> [--auto]
#
# What it does:
#   1. Probes wrangler auth — fails loudly if unauthenticated.
#   2. Confirms the deploy with the user (skipped if --auto + the customer
#      has profile.md → preferred_lookbook_host_auto: true).
#   3. Idempotently creates the Pages project (Wrangler v4+ requires this
#      before first `pages deploy`).
#   4. Runs scripts/validate-lookbook.py against the local artifact.
#   5. Deploys.
#   6. Runs scripts/validate-lookbook.py against the deployed URL.
#   7. Prints the URL.
#
# Flags:
#   --auto    Skip the per-publish confirmation prompt. The caller is
#             responsible for verifying preferred_lookbook_host_auto: true
#             upstream — this flag is just the wire.
#   --dry-run Build + validate locally; don't actually deploy.

set -euo pipefail

show_help() {
  cat <<'HELP'
Usage: scripts/deploy-lookbook.sh <deploy-dir> <project-name> [flags]

Deploys a built lookbook directory to Cloudflare Pages with probe + idempotent
project-create + local + deployed validation gates.

Arguments:
  <deploy-dir>      Local directory containing index.html + og.jpg + assets.
                    Must already pass scripts/validate-lookbook.py --dir.
  <project-name>    Cloudflare Pages project name. Becomes the stable alias
                    URL: https://<project-name>.pages.dev/

Flags:
  --auto            Skip the per-publish "Proceed? [y/N]" confirmation prompt.
                    The caller is responsible for verifying that the customer
                    has set profile.md → preferred_lookbook_host_auto: true
                    upstream — this flag is just the wire.
  --no-overwrite    Refuse to deploy if the named project already has prior
                    deployments. Use on every customer-facing recurring run
                    so the stable alias URL is permanent. See
                    references/hosting-options.md § "URL stability".
  --dry-run         Build + run local validation; skip the actual deploy.
  -h, --help        Show this help and exit.

Exit codes:
  0  success (or --dry-run completed)
  1  user aborted at confirmation prompt
  2  invalid arguments
  3  wrangler missing or unauthenticated
  4  --no-overwrite set but project has prior deployments
  (validate failures bubble through the underlying validate-lookbook.py exit
  codes; see scripts/validate-lookbook.py --help)

Examples:
  # Test/iteration deploy (single shared project, freely overwritten):
  bash scripts/deploy-lookbook.sh ./deploy buckmason-stylist-test

  # Production weekly newsletter (each lookbook gets a permanent project):
  bash scripts/deploy-lookbook.sh \
       ~/.buck-mason-stylist/runs/2026-weekly-19/deploy \
       buckmason-nick-2026-weekly-19 \
       --auto --no-overwrite
HELP
}

# --help / -h before positional parsing so help works regardless of position.
for arg in "$@"; do
  if [ "$arg" = "--help" ] || [ "$arg" = "-h" ]; then
    show_help; exit 0
  fi
done

DEPLOY_DIR="${1:-}"
PROJECT="${2:-}"
AUTO=0
DRY_RUN=0
NO_OVERWRITE=0
shift 2 || true
for arg in "$@"; do
  case "$arg" in
    --auto)         AUTO=1 ;;
    --dry-run)      DRY_RUN=1 ;;
    --no-overwrite) NO_OVERWRITE=1 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

if [ -z "$DEPLOY_DIR" ] || [ -z "$PROJECT" ]; then
  echo "usage: $0 <deploy-dir> <project-name> [--auto] [--dry-run]" >&2
  exit 2
fi
if [ ! -d "$DEPLOY_DIR" ]; then
  echo "error: deploy dir not found: $DEPLOY_DIR" >&2
  exit 2
fi
if [ ! -f "$DEPLOY_DIR/index.html" ]; then
  echo "error: $DEPLOY_DIR has no index.html — run scripts/build-html-lookbook.py first" >&2
  exit 2
fi

# 1. Probe wrangler auth.
if ! command -v wrangler >/dev/null 2>&1; then
  echo "error: wrangler not installed. Run: npm i -g wrangler" >&2
  exit 3
fi
if ! wrangler whoami >/dev/null 2>&1; then
  echo "error: wrangler is not authenticated. Run: wrangler login" >&2
  exit 3
fi
echo "✓ wrangler authenticated as: $(wrangler whoami 2>&1 | grep -oE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+' | head -1)"

# 2. Confirmation gate.
PAGE_URL="https://${PROJECT}.pages.dev/"
if [ $AUTO -eq 0 ] && [ $DRY_RUN -eq 0 ]; then
  echo
  echo "About to deploy '$DEPLOY_DIR' to: $PAGE_URL"
  echo "This URL will be public (anyone with the link can view)."
  printf "Proceed? [y/N] "
  read -r answer
  case "$answer" in
    y|Y|yes|YES) ;;
    *) echo "aborted by user."; exit 1 ;;
  esac
fi

# 3. Idempotent project create + URL-stability gate.
if wrangler pages project list 2>/dev/null | grep -qE "(^|[[:space:]])${PROJECT}([[:space:]]|$)"; then
  echo "✓ Pages project exists: $PROJECT"
  if [ $NO_OVERWRITE -eq 1 ]; then
    # The customer-facing URL stability rule: refuse to deploy if the project
    # already has a deployment, so a permanent lookbook URL never gets
    # silently overwritten. See references/hosting-options.md § "URL stability".
    # wrangler 4.x prints deployments as a Unicode box-drawing table; each
    # data row contains a UUID. Count UUIDs to count deployments.
    deploy_count=$(wrangler pages deployment list --project-name "$PROJECT" 2>/dev/null \
                   | grep -cE '[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}' || echo 0)
    if [ "$deploy_count" -gt 0 ]; then
      echo "error: --no-overwrite set, but project '$PROJECT' has $deploy_count prior deployment(s)." >&2
      echo "       Deploying would overwrite the stable alias https://${PROJECT}.pages.dev/." >&2
      echo "       Use a fresh project name, or drop --no-overwrite for test/iteration deploys." >&2
      exit 4
    fi
  fi
else
  echo "Creating Pages project: $PROJECT"
  wrangler pages project create "$PROJECT" --production-branch main
fi

# 4. Local validation.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo
echo "Running local validation..."
python3 "$SCRIPT_DIR/validate-lookbook.py" --dir "$DEPLOY_DIR"
echo "✓ local validation passed"

if [ $DRY_RUN -eq 1 ]; then
  echo
  echo "--dry-run: skipping wrangler pages deploy"
  exit 0
fi

# 5. Deploy.
echo
echo "Deploying..."
wrangler pages deploy "$DEPLOY_DIR" \
  --project-name "$PROJECT" \
  --branch main \
  --commit-dirty=true

# Give the CDN a few seconds to propagate before we curl it.
sleep 3

# 6. Deployed validation.
echo
echo "Running deployed validation against: $PAGE_URL"
python3 "$SCRIPT_DIR/validate-lookbook.py" --url "$PAGE_URL"
echo "✓ deployed validation passed"

# 7. Print URL (the only thing that goes to stdout for headless callers).
echo
echo "$PAGE_URL"
