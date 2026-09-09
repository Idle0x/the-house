"""Public-surface address redaction (audit SEV-2 / FIX-4c).

The house stores FULL addresses in the COLD journal + watch feed on purpose
(FIX-4: the ledger must reconcile against Basescan, so the tx + payer are kept
for the operator). The VIOLATION is that the FREE public routes
(``/house/journal``, ``/house/ledger`` recent, ``/house/watch`` feed,
``/house/jobs``) rendered those full addresses verbatim to anyone.

The fix is redaction at the PUBLIC BOUNDARY: the store keeps full, the public
render masks. An EVM-style identifier (``0x`` + 40 hex) becomes ``0x<last4>``
— the last-4 keeps the "which wallet" signal for the human reading the feed
while the first 36 chars (the identifying part) never leave the house. This is
a strict subset of the last-6 the ledger already used, so nothing that was
anonymized before is now less-anonymous.

Redaction is applied to TEXT (journal event strings) and to KNOWN address
fields (payer / wallet / caller / ring) on structured payloads. TX hashes are
deliberately NOT redacted — they are public onchain artifacts and are the
whole point of the reconciliation.
"""
from __future__ import annotations

import re
from typing import Any, Optional

# 0x + 40 hex (the real EVM address / tx shape that appears in journal text).
_ADDR = re.compile(r"0x[0-9a-fA-F]{40}")


def redact_text(text: str, preserve: frozenset = frozenset()) -> str:
    """Mask every full EVM-style identifier in a string to ``0x<last4>``.

    ``preserve`` is a set of literal strings (e.g. known tx hashes) that must
    NOT be masked — they are public onchain artifacts and the whole point of
    the ledger↔Basescan reconciliation. A settlement journal line embeds both
    the tx hash AND the full payer (both ``0x40`` hex); the tx is passed in
    ``preserve`` so it survives and the payer is masked. Non-address text and
    anything in ``preserve`` are left untouched.
    """
    if not text:
        return text

    def _repl(m):
        s = m.group(0)
        if s in preserve:
            return s
        return "0x" + s[-4:]

    return _ADDR.sub(_repl, text)


def redact_address(addr: Any) -> Optional[str]:
    """A single address field -> ``0x<last4>``, or the input short as-is when
    it is not a full address (already-anonymized last-6, a label, None)."""
    if not addr:
        return addr if isinstance(addr, str) else None
    s = str(addr)
    if _ADDR.fullmatch(s.strip()):
        return "0x" + s.strip()[-4:]
    return s  # not a full address — leave (last-6, label, etc.)


# Structured fields that, wherever they appear in a free-route payload, must
# be masked to 0x<last4>.
_ADDR_FIELDS = ("payer", "wallet", "caller", "address", "pay_to", "provider")


def redact_value(obj: Any, field: str = "") -> Any:
    """Recursively redact a payload: full-address strings in ``_ADDR_FIELDS``
    become 0x<last4>; list items that are addresses are masked; everything
    else passes through. TX hash fields are preserved verbatim."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in _ADDR_FIELDS:
                out[k] = redact_address(v)
            else:
                out[k] = redact_value(v, k)
        return out
    if isinstance(obj, list):
        return [redact_value(x, field) for x in obj]
    if isinstance(obj, str) and field in _ADDR_FIELDS:
        return redact_address(obj)
    return obj
