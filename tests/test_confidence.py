from app.confidence import score

EXTRACTION = {
    "vendor": "Acme Corp",
    "date": "2026-03-18",
    "invoice_no": "INV-001",
    "line_items": [{"description": "Widget", "quantity": 2.0, "unit_price": 5.0, "amount": 10.0}],
    "subtotal": 10.0,
    "tax": 0.8,
    "total": 10.8,
    "currency": "USD",
}
HIGH_CONF = dict.fromkeys(
    ["vendor", "date", "invoice_no", "line_items", "subtotal", "tax", "total", "currency"], 0.95
)


def test_clean_high_conf_auto_accepts():
    s = score(EXTRACTION, HIGH_CONF, [])
    assert s["route"] == "auto_accept"
    assert s["doc"] >= 0.9


def test_arithmetic_boost_lifts_financials():
    low = {**HIGH_CONF, "total": 0.6, "subtotal": 0.6}
    s = score(EXTRACTION, low, [])
    assert s["fields"]["total"] >= 0.97


def test_validation_error_forces_review_even_with_high_conf():
    issues = [{"field": "total", "code": "total_mismatch", "message": "x", "severity": "error"}]
    s = score(EXTRACTION, HIGH_CONF, issues)
    assert s["route"] == "needs_review"
    assert s["fields"]["total"] <= 0.30


def test_missing_required_zeroes_field():
    ex = {**EXTRACTION, "vendor": None}
    s = score(ex, HIGH_CONF, [])
    assert s["fields"]["vendor"] == 0.0


def test_missing_optional_excluded_not_penalized():
    ex = {**EXTRACTION, "invoice_no": None}
    s = score(ex, HIGH_CONF, [])
    assert s["fields"]["invoice_no"] is None
    assert s["route"] == "auto_accept"


def test_parse_failure_routes_review():
    s = score({}, {}, [], parse_failed=True)
    assert s["route"] == "needs_review"
    assert s["doc"] == 0.0


def test_low_model_conf_routes_review():
    lowall = dict.fromkeys(HIGH_CONF, 0.4)
    ex = {**EXTRACTION, "line_items": [], "subtotal": None, "tax": None}
    s = score(ex, lowall, [])
    assert s["route"] == "needs_review"
