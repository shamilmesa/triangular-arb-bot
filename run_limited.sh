#!/bin/bash
# Runs a script in this repo's venv under the resource limits used
# throughout this project's VDS testing (nice/ionice + a systemd scope
# capped at 700M memory).
#
# Uses the venv's python3 directly by absolute path -- forgetting to
# `source .venv/bin/activate` in a fresh shell is the single most common
# error seen throughout this project (ModuleNotFoundError: No module
# named 'dotenv'), so this sidesteps needing an active venv at all.
#
# Why the resource limits: this repo's testing runs on the same VDS as
# an unrelated, longer-running test in a different repo/directory, and
# must not compete with it for CPU/memory.
#
# Usage:
#   ./run_limited.sh src/historical_scan_triangular.py \
#     --token-b 0x... --token-c 0x... --start N --end M --step S
#   ./run_limited.sh src/simulate_triangular_arbitrage.py --token-c 0x...

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$SCRIPT_DIR/.venv/bin/python3"

if [ ! -x "$PYTHON" ]; then
  echo "No venv found at $SCRIPT_DIR/.venv -- create it first:" >&2
  echo "  python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt" >&2
  exit 1
fi

exec nice -n 15 ionice -c3 systemd-run --scope -p MemoryMax=700M --user "$PYTHON" "$@"
