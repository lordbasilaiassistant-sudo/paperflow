from app.export import export_csv
from app.extract import _find_json


def test_plain_json():
    assert _find_json('{"a": 1}') == {"a": 1}


def test_fenced_json():
    assert _find_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_json_with_prose():
    assert _find_json('Here is the extraction:\n{"a": {"b": 2}}\nHope that helps!') == {"a": {"b": 2}}


def test_braces_inside_strings():
    assert _find_json('{"desc": "a {weird} value"}') == {"desc": "a {weird} value"}


def test_no_json():
    assert _find_json("I cannot extract this document.") is None


def test_truncated_json():
    assert _find_json('{"a": 1, "b": ') is None


def test_export_documents_csv():
    docs = [{
        "id": "abc", "filename": "inv.pdf", "doc_confidence": 0.95, "updated_at": "2026-07-17",
        "extraction": {
            "vendor": "Acme", "date": "2026-03-18", "invoice_no": "1", "currency": "USD",
            "subtotal": 10.0, "tax": 0.8, "total": 10.8,
            "line_items": [{"description": "W, with comma", "quantity": 1, "unit_price": 10.0, "amount": 10.0}],
        },
    }]
    out = export_csv(docs, "documents")
    lines = out.strip().split("\n")
    assert len(lines) == 2
    assert "Acme" in lines[1]

    items = export_csv(docs, "line_items")
    assert '"W, with comma"' in items
