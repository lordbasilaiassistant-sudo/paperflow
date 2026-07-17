from app.normalize import normalize_extraction, parse_amount, parse_currency, parse_date


def test_amount_plain():
    assert parse_amount("1234.56") == 1234.56
    assert parse_amount(42) == 42.0
    assert parse_amount(None) is None
    assert parse_amount("") is None


def test_amount_us_thousands():
    assert parse_amount("$1,234.56") == 1234.56
    assert parse_amount("12,345") == 12345.0


def test_amount_european():
    assert parse_amount("1.234,56") == 1234.56
    assert parse_amount("€99,50") == 99.50


def test_amount_negative():
    assert parse_amount("-45.00") == -45.00
    assert parse_amount("(45.00)") == -45.00


def test_amount_garbage():
    assert parse_amount("N/A") is None
    assert parse_amount("-") is None


def test_date_formats():
    assert parse_date("2026-03-18") == "2026-03-18"
    assert parse_date("03/18/2026") == "2026-03-18"
    assert parse_date("March 18, 2026") == "2026-03-18"
    assert parse_date("18 Mar 2026") == "2026-03-18"
    assert parse_date("18.03.2026") == "2026-03-18"
    assert parse_date("Mar 3rd, 2026") == "2026-03-03"


def test_date_unparseable():
    assert parse_date("sometime last week") is None
    assert parse_date(None) is None


def test_currency():
    assert parse_currency("usd") == "USD"
    assert parse_currency("$") == "USD"
    assert parse_currency("€") == "EUR"
    assert parse_currency("dollars") is None
    assert parse_currency(None) is None


def test_normalize_extraction_roundtrip():
    raw = {
        "vendor": "  Acme Corp  ",
        "date": "03/18/2026",
        "invoice_no": "INV-001",
        "line_items": [{"description": "Widget", "quantity": "2", "unit_price": "$5.00", "amount": "$10.00"}],
        "subtotal": "10.00",
        "tax": "0.80",
        "total": "$10.80",
        "currency": "$",
    }
    out = normalize_extraction(raw)
    assert out["vendor"] == "Acme Corp"
    assert out["date"] == "2026-03-18"
    assert out["total"] == 10.80
    assert out["currency"] == "USD"
    assert out["line_items"][0]["amount"] == 10.00
    assert out["line_items"][0]["quantity"] == 2.0
