#!/usr/bin/env sh
# Slice 2B Batch B browser gate. Equivalent behaviour to browser-test.ps1.
set -eu

project="${BROWSER_TEST_PROJECT:-ha_stage5_2b_browser}"
url="${PLAYWRIGHT_TEST_BASE_URL:-http://127.0.0.1:18080}"
stub_url="${SYSTEM_TEST_STUB_URL:-http://127.0.0.1:18091}"
fake_exec_url="${SYSTEM_TEST_FAKE_EXEC_URL:-http://127.0.0.1:18092}"
fake_wolfram_url="${SYSTEM_TEST_FAKE_WOLFRAM_URL:-http://127.0.0.1:18093}"

# Run from a subshell so the EXIT trap cleans up from the repo root regardless
# of the caller's working directory (otherwise docker-compose files won't resolve).
(
  root="$(cd "$(dirname "$0")/.." && pwd)"
  cd "$root"

  F="-f docker-compose.yml -f compose.system-test.yml"
  cleanup() {
    docker compose -p "$project" $F down --volumes --remove-orphans
  }
  trap cleanup EXIT INT TERM

  # Full tool stack: web + both workers + probe (+deps incl. fakes, mcp-execution).
  docker compose -p "$project" $F up --build --detach web practice-worker tutor-system-worker capability-probe

  # Readiness poll (no fixed sleep): wait for the web root. Capability readiness
  # is enforced by the seed scripts' wait_for_environment inside the runner.
  attempt=0
  until curl --fail --silent --show-error "$url" >/dev/null; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 90 ]; then
      echo "environment_failed:web_not_ready" >&2
      exit 1
    fi
    sleep 1
  done

  docker compose -p "$project" $F run --build --rm --no-deps system-test-runner \
    python tests/system/seed_browser_tutor.py
  docker compose -p "$project" $F run --build --rm --no-deps system-test-runner \
    python tests/system/seed_browser_tools.py

  (
    cd apps/web
    PLAYWRIGHT_TEST_BASE_URL="$url" \
    SYSTEM_TEST_STUB_URL="$stub_url" \
    SYSTEM_TEST_FAKE_EXEC_URL="$fake_exec_url" \
    SYSTEM_TEST_FAKE_WOLFRAM_URL="$fake_wolfram_url" \
    npm run test:e2e
  )
)
