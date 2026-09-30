import pytest

from app.utils.phone import extract_phones, normalize_phone, phones_match, search_variants, to_tel

SAME = ["0561234567", "966561234567", "+966561234567", "+966 56 123 4567", "05 6123 4567",
        "00966561234567", "561234567", "٠٥٦١٢٣٤٥٦٧", "+966 (0)56-123-4567", "9660561234567"]


@pytest.mark.parametrize("raw", SAME)
def test_saudi_variants_normalize_to_same_number(raw):
    assert normalize_phone(raw) == "966561234567"


def test_empty_and_garbage():
    assert normalize_phone(None) == ""
    assert normalize_phone("") == ""
    assert normalize_phone("لا يوجد") == ""


def test_landline_and_foreign():
    assert normalize_phone("0112345678") == "966112345678"
    assert normalize_phone("+20 100 123 4567") == "201001234567"


def test_phones_match():
    assert phones_match("05 6123 4567", "+966561234567")
    assert not phones_match("0561234567", "0561234568")
    assert not phones_match("", "0561234567")


def test_extract_multiple_numbers_in_one_cell():
    assert extract_phones("0561234567 / 0551112222") == ["966561234567", "966551112222"]
    assert extract_phones("+966 56 123 4567") == ["966561234567"]


def test_search_variants_and_tel():
    v = search_variants("0561234567")
    assert "561234567" in v and "0561234567" in v and "+966 56 123 4567" in v
    assert to_tel("05 6123 4567") == "+966561234567"


@pytest.mark.parametrize("raw,severity,kind,issue", [
    ("0561234567", "ok", "mobile", None),
    ("+966 56 123 4567", "ok", "mobile", None),
    ("٠٥٦١٢٣٤٥٦٧", "ok", "mobile", None),
    ("0114567890", "ok", "landline", None),
    ("920012345", "ok", "unified", None),
    ("056123456", "error", "invalid", "ناقص 1 رقم"),
    ("05612345678", "error", "invalid", "زائد 1 رقم"),
    ("abc0561", "error", "invalid", "حروف"),
    ("", "error", "empty", "لا يوجد رقم"),
    ("12345", "error", "invalid", "غير معروفة"),
    ("0500000000", "warning", "mobile", "وهميًا"),
    ("0561234567 / 0551112222", "warning", "mobile", "أكثر من رقم"),
    ("+971501234567", "warning", "international", "دولي"),
])
def test_check_phone(raw, severity, kind, issue):
    from app.utils.phone import check_phone
    r = check_phone(raw)
    assert r["severity"] == severity and r["kind"] == kind
    assert (issue is None and r["issues"] == []) or any(issue in i for i in r["issues"])
