"""Saudi-aware phone number normalization.

All phone comparisons in the agent go through :func:`normalize_phone` so that
``0561234567``, ``966561234567``, ``+966 56 123 4567`` and ``05 6123 4567``
are all treated as the same number (``966561234567``).
"""
from __future__ import annotations

import re

SAUDI_CC = "966"

# Arabic-Indic (U+0660..U+0669) and Extended Arabic-Indic (U+06F0..U+06F9) digits.
_DIGIT_TRANSLATION = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
    "01234567890123456789",
)
_SPLIT_RE = re.compile(r"[/,;|\n]+|\s{3,}|\s+(?:او|أو|or)\s+", re.IGNORECASE)


def to_ascii_digits(value: str) -> str:
    """Convert Arabic-Indic digits to ASCII digits."""
    return value.translate(_DIGIT_TRANSLATION)


def normalize_phone(raw: str | None) -> str:
    """Return a canonical digits-only phone number.

    Saudi numbers are returned in international form without ``+``
    (``9665XXXXXXXX``). Non-Saudi numbers are returned as plain digits with any
    ``00`` international prefix removed. Returns ``""`` for empty/invalid input.
    """
    if not raw:
        return ""
    text = to_ascii_digits(str(raw)).strip()
    digits = re.sub(r"\D", "", text)
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    # 9660561234567 -> 966561234567 (a trunk zero kept after the country code)
    if digits.startswith(SAUDI_CC + "0"):
        digits = SAUDI_CC + digits[4:]
    if digits.startswith(SAUDI_CC) and len(digits) == 12:
        return digits
    # Local mobile/landline with trunk prefix: 05XXXXXXXX / 01XXXXXXXX
    if digits.startswith("0") and len(digits) == 10:
        return SAUDI_CC + digits[1:]
    # Local mobile without trunk prefix: 5XXXXXXXX
    if digits.startswith("5") and len(digits) == 9:
        return SAUDI_CC + digits
    return digits


def extract_phones(raw: str | None) -> list[str]:
    """Split a cell that may contain several numbers and normalize each one."""
    if not raw:
        return []
    text = to_ascii_digits(str(raw))
    parts = [p for p in _SPLIT_RE.split(text) if p and p.strip()]
    result: list[str] = []
    for part in parts:
        norm = normalize_phone(part)
        if len(norm) >= 7 and norm not in result:
            result.append(norm)
    if not result:
        norm = normalize_phone(text)
        if norm:
            result.append(norm)
    return result


def phones_match(a: str | None, b: str | None) -> bool:
    """True when two raw phone values refer to the same number."""
    na, nb = normalize_phone(a), normalize_phone(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # Tolerate a missing/foreign country code when the subscriber part is long enough.
    return len(na) >= 9 and len(nb) >= 9 and na[-9:] == nb[-9:]


def national_significant(norm: str) -> str:
    """Last 9 digits (subscriber part for Saudi mobiles)."""
    return norm[-9:] if len(norm) >= 9 else norm


def search_variants(raw: str | None) -> list[str]:
    """Formats commonly stored in Odoo, used to build ``ilike`` searches."""
    norm = normalize_phone(raw)
    if not norm:
        return []
    variants = [norm, national_significant(norm)]
    if norm.startswith(SAUDI_CC) and len(norm) == 12:
        local = "0" + norm[3:]
        sub = norm[3:]
        variants += [
            local,
            "+" + norm,
            f"+966 {sub[:2]} {sub[2:5]} {sub[5:]}",
            f"0{sub[:2]} {sub[2:5]} {sub[5:]}",
            f"0{sub[:1]} {sub[1:5]} {sub[5:]}",
        ]
    out: list[str] = []
    for v in variants:
        if v and v not in out:
            out.append(v)
    return out


def to_tel(raw: str | None) -> str:
    """E.164-like representation used for ``tel:`` links."""
    norm = normalize_phone(raw)
    return f"+{norm}" if norm else ""
