#!/usr/bin/env bash
# Portable compatibility wrapper; requires an explicit credential-file argument.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$root/setup_local.py" --register-codex "$@"
