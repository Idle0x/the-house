#!/usr/bin/env bash
# THE HOUSE — scripted, reproducible Base mainnet payment (GATE 3).
#
# One real x402 USDC payment to the house's paid route, executed by script
# (not hand-keyed), with the settlement tx hash logged to data/payments.log
# and printed for Basescan. Run it twice and the second call is a $0 dedup
# repeat (the F2 money beat on camera).
#
# Usage:
#   scripts/pay.sh [route] [buyer-key-file]
#     route          default /intel/quote   (the house's paid route)
#     buyer-key-file default /root/projects/x402-lab/.lab_key
#
# Env:
#   HOUSE_SELLER    default http://localhost:8090
#   HOUSE_BUYER_KEY hex private key; if unset, read from the key file arg.
set -euo pipefail

cd "$(dirname "$0")/.."   # repo root — buyer.py resolves its own paths

ROUTE="${1:-/intel/quote}"
KEYFILE="${2:-/root/projects/x402-lab/.lab_key}"
LOG="data/payments.log"
PY=".venv/bin/python"

if [[ ! -f "$KEYFILE" ]]; then
    echo "ERROR: buyer key file not found: $KEYFILE" >&2
    exit 2
fi

export HOUSE_BUYER_KEY="${HOUSE_BUYER_KEY:-$(cat "$KEYFILE")}"
export HOUSE_SELLER="${HOUSE_SELLER:-http://localhost:8090}"

TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "=== THE HOUSE — pay.sh (Gate 3) ==="
echo "[$TS] route     : ${HOUSE_SELLER}${ROUTE}"
echo "[$TS] buyer key : $KEYFILE (not printed)"

# Run the buyer; capture the full receipt. tee so the human sees it live.
OUT="$("$PY" scripts/buyer.py "$ROUTE" 2>&1 | tee /dev/stderr)"

# Extract the settlement tx hash from the buyer's receipt.
TXH="$(printf '%s' "$OUT" | sed -n 's/.*settlement tx : \(0x[0-9a-fA-F]*\).*/\1/p' | head -1)"

mkdir -p data
if [[ -n "${TXH:-}" ]]; then
    echo "[$TS] $ROUTE tx=$TXH" >> "$LOG"
    echo ""
    echo "=== SETTLEMENT LOGGED ==="
    echo "tx   : $TXH"
    echo "scan : https://basescan.org/tx/$TXH"
    echo "log  : $LOG"
    exit 0
fi

# No tx hash: the payment did not settle. Exit nonzero (Gate 3 fails).
echo "ERROR: no settlement tx in buyer output — payment did NOT settle." >&2
echo "[$TS] $ROUTE NO-SETTLEMENT" >> "$LOG"
exit 1
