"""Input-identity validation for the house's public routes.

The house keys ALL of its memory (trust, dedup, bonds, watch, journal, scout)
by a counterparty *identifier*. In this system an identifier is a
``0x``-prefixed 40-char string — the same shape as an EVM address, but the
house also keys some entities by a 40-char derived label, so the contract the
code actually honours is **shape**, not **hex**:

    ``0x`` + exactly 40 alphanumeric chars

This module enforces that shape at the HTTP boundary (
``front.decision`` / ``dossier._short`` / ``scout`` did ``[-6:]`` on
arbitrary user strings, and ``POST /scout/hire {provider: "hello"}`` would
write a junk provider row into memory). The fix is a single reusable check so
every route that takes a wallet/provider/insured identifier rejects junk
BEFORE any memory is touched — a 400/422 cancels the x402 settlement, so a
malformed request is genuinely uncharged.

Why shape, not strict-hex: the executable spec (the test corpus) keys entities
by non-hex 40-char placeholders (``"0x"+"S"*40``), so strict EVM-hex would
break the whole corpus for a finding the audit itself rated "minor". If a
deploy needs *strict EVM* (hex-only) addresses, tighten ``_HEX40`` — the
rest of the boundary code is unchanged.
"""
from __future__ import annotations

import re
from typing import Optional

# ``0x`` + 40 alphanumeric chars — the identifier shape the house keys by.
# (Strict EVM hex would be ``[0-9a-fA-F]{40}``; see module docstring.)
_WALLET = re.compile(r"^0x[0-9a-zA-Z]{40}$")


def is_wallet(value: object) -> bool:
    """True iff ``value`` is a ``0x``-prefixed 40-alphanumeric identifier.

    Rejects: non-strings, empty/whitespace, missing ``0x`` prefix, wrong
    length (e.g. ``"0x123"`` or 41 chars), and non-alphanumeric bodies.
    """
    if not isinstance(value, str):
        return False
    return _WALLET.match(value.strip()) is not None


def require_wallet(value: object, field: str = "address") -> Optional[str]:
    """Return the normalized (stripped) identifier, or None if invalid.

    A thin helper for routes: ``ident = require_wallet(body.get("provider"),
    "provider")``; ``if ident is None: return 400``. Keeps each route to a
    two-liner instead of repeating the regex.
    """
    if isinstance(value, str) and is_wallet(value):
        return value.strip()
    return None
