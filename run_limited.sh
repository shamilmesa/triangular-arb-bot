#!/bin/bash
# Runs any command in this repo under the resource limits used
# throughout this project's VDS testing (nice/ionice + a systemd scope
# capped at 700M memory), so you don't have to type nice/ionice/
# systemd-run by hand before every invocation.
#
# Why this matters: this repo's testing runs on the same VDS as an
# unrelated, longer-running test in a different repo/directory, and
# must not compete with it for CPU/memory.
#
# Usage:
#   ./run_limited.sh python3 src/historical_scan_triangular.py \
#     --token-b 0x... --token-c 0x... --start N --end M --step S
#   ./run_limited.sh python3 src/simulate_triangular_arbitrage.py --token-c 0x...

set -euo pipefail
exec nice -n 15 ionice -c3 systemd-run --scope -p MemoryMax=700M --user "$@"
