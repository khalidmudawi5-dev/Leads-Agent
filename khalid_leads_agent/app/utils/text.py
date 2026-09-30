"""Deterministic text normalization helpers (no AI / fuzzy guessing of identity)."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from difflib import SequenceMatcher

_ARABIC_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_SPACES = re.compile(r"\s+")
_PUNCT = re.compile(r"[\"'`«»“”‘’.,،؛:;!؟?()\[\]{}<>\-_/\\|*+=~^&%$#@]")
_COMPANY_STOPWORDS = {
    "شركة", "مؤسسة", "مجموعة", "مكتب", "co", "company", "est", "llc", "ltd",
    "المحدودة", "محدودة", "للتجارة", "التجارية",
}


def normalize_text(value: str | None) -> str:
    """NFKC, strip tatweel/diacritics, collapse spaces, casefold."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = _ARABIC_DIACRITICS.sub("", text)
    text = _SPACES.sub(" ", text).strip()
    return text.casefold()


def normalize_arabic_letters(value: str) -> str:
    """Unify common Arabic letter variants (أ/إ/آ→ا, ة→ه, ى→ي)."""
    return (
        value.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
        .replace("ة", "ه").replace("ى", "ي")
    )


def normalize_company(value: str | None) -> str:
    """Normalized company name used for fingerprints and exact matching."""
    text = normalize_arabic_letters(normalize_text(value))
    text = _PUNCT.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def company_core(value: str | None) -> str:
    """Company name without generic words (شركة، مؤسسة، LLC...) for partial matching."""
    words = [w for w in normalize_company(value).split(" ") if w and w not in _COMPANY_STOPWORDS]
    return " ".join(words)


def company_similarity(a: str | None, b: str | None) -> float:
    """0..1 similarity ratio between two company names (used for candidates only)."""
    ca, cb = company_core(a), company_core(b)
    if not ca or not cb:
        return 0.0
    if ca == cb:
        return 1.0
    if ca in cb or cb in ca:
        return 0.9
    return SequenceMatcher(None, ca, cb).ratio()


def same_person(a: str | None, b: str | None) -> bool:
    """Owner comparison (e.g. "خالد" vs " خالد ")."""
    return normalize_arabic_letters(normalize_text(a)) == normalize_arabic_letters(normalize_text(b))


def make_fingerprint(company: str | None, phone_norm: str, owner: str | None) -> str:
    """Stable local identity of a sheet lead: company + phone + owner (not row number)."""
    key = "|".join([normalize_company(company), phone_norm or "", normalize_arabic_letters(normalize_text(owner))])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]


def html_to_text(html: str | None) -> str:
    """Very small HTML → text converter for chatter bodies."""
    if not html:
        return ""
    text = re.sub(r"<\s*br\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"</\s*p\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    import html as _html

    return _html.unescape(text).strip()
