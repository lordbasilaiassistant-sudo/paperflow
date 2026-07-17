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
# Source text that actually contains the extracted values (so they ground).
SOURCE = (
    "Acme Corp\nInvoice #: INV-001\nDate: 03/18/2026\n"
    "Widget  2  5.00  10.00\nSubtotal: 10.00\nTax: 0.80\nTOTAL: 10.80\n"
)


def test_clean_high_conf_grounded_auto_accepts():
    s = score(EXTRACTION, HIGH_CONF, [], raw_text=SOURCE)
    assert s["route"] == "auto_accept"
    assert s["doc"] >= 0.9


def test_arithmetic_boost_lifts_grounded_financials():
    low = {**HIGH_CONF, "total": 0.6, "subtotal": 0.6}
    s = score(EXTRACTION, low, [], raw_text=SOURCE)
    assert s["fields"]["total"] >= 0.90


def test_hallucinated_total_not_in_source_does_not_auto_accept():
    # The critical false-accept case: model returns a fully self-consistent but
    # WRONG set of numbers that never appears on the page.
    hallucinated = {
        **EXTRACTION,
        "line_items": [{"description": "Widget", "quantity": 2.0, "unit_price": 71.0, "amount": 142.0}],
        "subtotal": 130.0, "tax": 12.0, "total": 142.0,
    }
    s = score(hallucinated, HIGH_CONF, [], raw_text=SOURCE)  # SOURCE has none of these numbers
    assert s["route"] == "needs_review"
    assert s["fields"]["total"] <= 0.45


def test_validation_error_forces_review():
    issues = [{"field": "vendor", "code": "missing_required", "message": "x", "severity": "error"}]
    ex = {**EXTRACTION, "vendor": None}
    s = score(ex, HIGH_CONF, issues, raw_text=SOURCE)
    assert s["route"] == "needs_review"


def test_wrong_vendor_blocks_auto_accept_despite_good_financials():
    # Financials reconcile and ground, but the vendor is not on the page.
    ex = {**EXTRACTION, "vendor": "Totally Different Co"}
    s = score(ex, HIGH_CONF, [], raw_text=SOURCE)
    assert s["route"] == "needs_review"


def test_missing_required_zeroes_field():
    ex = {**EXTRACTION, "total": None}
    issues = [{"field": "total", "code": "missing_required", "message": "x", "severity": "error"}]
    s = score(ex, HIGH_CONF, issues, raw_text=SOURCE)
    assert s["fields"]["total"] == 0.0
    assert s["route"] == "needs_review"


def test_missing_optional_excluded_not_penalized():
    ex = {**EXTRACTION, "invoice_no": None}
    s = score(ex, HIGH_CONF, [], raw_text=SOURCE)
    assert s["fields"]["invoice_no"] is None
    assert s["route"] == "auto_accept"


def test_parse_failure_routes_review():
    s = score({}, {}, [], parse_failed=True)
    assert s["route"] == "needs_review"
    assert s["doc"] == 0.0


def test_trivial_reconciliation_does_not_boost():
    # subtotal == total, no line items: not independent corroboration.
    ex = {"vendor": "Acme Corp", "date": "2026-03-18", "invoice_no": None,
          "line_items": [], "subtotal": 500.0, "tax": None, "total": 500.0, "currency": "USD"}
    src = "Acme Corp\nDate: 03/18/2026\nTOTAL: 500.00\n"
    s = score(ex, dict.fromkeys(HIGH_CONF, 0.5), [], raw_text=src)
    # total should reflect model conf (0.5), not a 0.90 boost from 500==500.
    assert s["fields"]["total"] < 0.90


def test_no_source_text_falls_back_to_model_confidence():
    # Grounding is skipped when no text is available; behaves like the prior model.
    s = score(EXTRACTION, HIGH_CONF, [], raw_text="")
    assert s["route"] == "auto_accept"
