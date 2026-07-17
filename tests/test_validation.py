from app.validation import validate

GOOD = {
    "vendor": "Acme Corp",
    "date": "2026-03-18",
    "invoice_no": "INV-001",
    "line_items": [
        {"description": "Widget", "quantity": 2.0, "unit_price": 5.0, "amount": 10.0},
        {"description": "Gadget", "quantity": 1.0, "unit_price": 15.0, "amount": 15.0},
    ],
    "subtotal": 25.0,
    "tax": 2.0,
    "total": 27.0,
    "currency": "USD",
}


def codes(issues):
    return {i["code"] for i in issues}


def test_clean_doc_passes():
    assert validate(GOOD) == []


def test_missing_required():
    doc = {**GOOD, "vendor": None, "total": None}
    got = codes(validate(doc))
    assert "missing_required" in got


def severities(issues, code):
    return {i["severity"] for i in issues if i["code"] == code}


def test_line_sum_mismatch_is_warning():
    doc = {**GOOD, "subtotal": 30.0, "total": 32.0, "tax": 2.0}
    issues = validate(doc)
    assert "sum_mismatch" in codes(issues)
    # A mismatch may be a legit discount/shipping row, so it's a warning, not an error.
    assert severities(issues, "sum_mismatch") == {"warning"}


def test_total_mismatch_is_warning():
    doc = {**GOOD, "total": 99.0}
    issues = validate(doc)
    assert "total_mismatch" in codes(issues)
    assert severities(issues, "total_mismatch") == {"warning"}


def test_total_check_skipped_when_tax_missing():
    # Missing tax must not be treated as 0 (that would let subtotal == total reconcile falsely).
    doc = {**GOOD, "tax": None, "subtotal": 25.0, "total": 25.0}
    assert "total_mismatch" not in codes(validate(doc))


def test_adjustments_total_does_not_error():
    # discount + shipping: total legitimately != subtotal + tax -> warning only, no error
    doc = {**GOOD, "subtotal": 25.0, "tax": 2.0, "total": 22.0}  # 25+2-5 discount
    issues = validate(doc)
    assert not any(i["severity"] == "error" for i in issues)


def test_tolerance_penny():
    doc = {**GOOD, "total": 27.01}
    # within ±0.01 -> no arithmetic error
    assert "total_mismatch" not in codes(validate(doc))


def test_bad_date():
    doc = {**GOOD, "date": "18/03/2026 ish"}
    assert "bad_date" in codes(validate(doc))


def test_line_items_vs_total_when_no_subtotal():
    doc = {**GOOD, "subtotal": None}
    assert validate(doc) == []
    doc2 = {**GOOD, "subtotal": None, "total": 40.0}
    assert "sum_mismatch" in codes(validate(doc2))


def test_negative_credit_note():
    doc = {
        **GOOD,
        "line_items": [{"description": "Refund", "quantity": 1.0, "unit_price": -27.0, "amount": -27.0}],
        "subtotal": -27.0,
        "tax": 0.0,
        "total": -27.0,
    }
    assert validate(doc) == []


def test_item_math_warning():
    doc = {
        **GOOD,
        "line_items": [
            {"description": "Widget", "quantity": 2.0, "unit_price": 5.0, "amount": 25.0},
        ],
        "subtotal": 25.0,
    }
    issues = validate(doc)
    assert "item_math" in codes(issues)
    assert all(i["severity"] == "warning" for i in issues if i["code"] == "item_math")
