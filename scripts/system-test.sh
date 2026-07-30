#!/usr/bin/env sh
# Slice 2B Batch B controlled-system gate. Equivalent behaviour to system-test.ps1.
set -eu

(
  root="$(cd "$(dirname "$0")/.." && pwd)"
  cd "$root"

  project="${SYSTEM_TEST_PROJECT:-ha_stage5_2b}"
  F="-f docker-compose.yml -f compose.system-test.yml"
  cleanup() {
    docker compose -p "$project" $F down --volumes --remove-orphans
  }
  trap cleanup EXIT INT TERM

  docker compose -p "$project" $F \
    up --build --abort-on-container-exit --exit-code-from system-test-runner system-test-runner
)
