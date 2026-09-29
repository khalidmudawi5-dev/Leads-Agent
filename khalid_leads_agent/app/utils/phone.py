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


# --------------------------------------------------------------- validation
_LETTERS_RE = re.compile(r"[A-Za-z؀-ٟٮ-ۯۺ-ۿ]")


def check_phone(raw: str | None) -> dict:
    """Deterministic sanity check of a phone value (Saudi-aware) before calling it.

    Returns ``{"raw", "norm", "tel", "valid", "severity", "kind", "issues"}`` where
    ``severity`` is ``ok`` | ``warning`` (callable, but look) | ``error`` (do not call as-is)
    and ``kind`` is ``mobile`` | ``landline`` | ``unified`` | ``international`` | ``invalid`` | ``empty``.
    """
    raw = (raw or "").strip()
    out = {"raw": raw, "norm": "", "tel": "", "valid": False, "severity": "error", "kind": "invalid", "issues": []}
    issues: list[str] = out["issues"]
    if not raw:
        out["kind"] = "empty"
        issues.append("لا يوجد رقم")
        return out
    text = to_ascii_digits(raw)
    parts = [p for p in _SPLIT_RE.split(text) if p and re.sub(r"\D", "", p)]
    warn: list[str] = []
    if len(parts) > 1:
        warn.append(f"الحقل يحتوي على أكثر من رقم ({len(parts)})؛ سيتم استخدام الأول")
        text = parts[0]
    if _LETTERS_RE.search(text):
        issues.append("الرقم يحتوي على حروف")
        return out
    digits = re.sub(r"\D", "", text)
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("9660"):
        digits = "966" + digits[4:]
    # Unified / toll-free numbers (9200XXXXX, 800XXXXXXX)
    if (digits.startswith("9200") and len(digits) == 9) or (digits.startswith("800") and len(digits) == 10):
        out.update(norm=digits, tel=digits, valid=True, kind="unified")
    else:
        if digits.startswith("966"):
            sub = digits[3:]
        elif digits.startswith("0"):
            sub = digits[1:]
        elif digits.startswith("5") and len(digits) <= 10:
            sub = digits
        elif 8 <= len(digits) <= 15:
            out.update(norm=digits, tel="+" + digits, valid=True, kind="international")
            warn.append("رقم دولي (ليس سعوديًا)")
            sub = None
        else:
            issues.append(f"صيغة الرقم غير معروفة ({len(digits)} رقم)")
            return out
        if sub is not None:
            is_mobile = sub.startswith("5")
            if len(sub) == 9 and (is_mobile or sub[0] in "134679"):
                out.update(norm="966" + sub, tel="+966" + sub, valid=True, kind="mobile" if is_mobile else "landline")
            else:
                expected = 10  # 05XXXXXXXX / 01XXXXXXXX
                local_len = len(sub) + 1
                label = "رقم الجوال" if is_mobile else "الرقم"
                if local_len < expected:
                    issues.append(f"{label} ناقص {expected - local_len} رقم (المفترض {expected} أرقام مثل 05XXXXXXXX)")
                elif local_len > expected:
                    issues.append(f"{label} زائد {local_len - expected} رقم (المفترض {expected} أرقام مثل 05XXXXXXXX)")
                else:
                    issues.append("بداية الرقم غير صحيحة لرقم سعودي")
                return out
    sub9 = out["norm"][-9:]
    if out["kind"] in ("mobile", "landline") and (len(set(sub9[1:])) == 1 or sub9[1:] in ("12345678", "87654321")):
        warn.append("الرقم يبدو وهميًا أو تجريبيًا")
    issues.extend(warn)
    out["severity"] = "warning" if warn else "ok"
    return out
