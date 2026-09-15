#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

skills=$(find skills -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort -u)

# Tracked files only: ignored build/agent artifacts carry placeholder skill
# references that are not this repo's problem.
refs=$(git ls-files -z -- '*.md' '*.json' '*.sh' \
  | xargs -0 -r grep -hoE 'knowledge-gardener:[a-z][a-z0-9-]*' 2>/dev/null \
  | sed 's/^knowledge-gardener://' \
  | sort -u || true)

fail=0
while IFS= read -r ref; do
  [ -z "$ref" ] && continue
  if ! grep -qx "$ref" <<<"$skills"; then
    echo "Unknown skill reference: knowledge-gardener:$ref" >&2
    fail=1
  fi
done <<<"$refs"

exit $fail
