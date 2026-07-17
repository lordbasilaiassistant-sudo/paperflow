"""Deterministic cleanup of raw LLM output before validation.

The model returns what it saw; this module makes it comparable: amounts become
floats, dates become ISO, currency becomes a 3-letter code. Anything that can't
be normalized is left as-is so validation can flag it instead of silently
dropping data.
"""

import re
from datetime import datetime

CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR"}

DATE_FORMATS = [
    "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m-%d-%Y", "%d-%m-%Y",
    "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%Y/%m/%d",
    "%m/%d/%y", "%d.%m.%Y", "%Y.%m.%d",
]


def parse_amount(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    s = str(value).strip()
    if not s:
        return None
    negative = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[^\d.,\-]", "", s)
    if not s or s in ("-", ".", ","):
        return None
    # 1.234,56 (European) vs 1,234.56 (US): whichever separator comes last is the decimal point.
    if "," in s and "." in s:
        if s.rindex(",") > s.rindex("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # A lone comma followed by exactly 2 digits is a decimal comma; otherwise a thousands separator.
        if re.search(r",\d{2}$", s) and not re.search(r",\d{3}$", s):
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return round(-v if negative else v, 2)


def parse_date(value) -> str | None:
    """Return ISO YYYY-MM-DD, or None if the value can't be parsed."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", s)
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_currency(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s in CURRENCY_SYMBOLS:
        return CURRENCY_SYMBOLS[s]
    s = s.upper()
    if re.fullmatch(r"[A-Z]{3}", s):
        return s
    return None


def normalize_extraction(raw: dict) -> dict:
    """Normalize a raw extraction dict in place-safe fashion; returns a new dict."""
    out = dict(raw)
    for f in ("subtotal", "tax", "total"):
        out[f] = parse_amount(raw.get(f))
    out["date"] = parse_date(raw.get("date")) or (str(raw.get("date")).strip() if raw.get("date") else None)
    out["currency"] = parse_currency(raw.get("currency"))
    for f in ("vendor", "invoice_no"):
        v = raw.get(f)
        out[f] = str(v).strip() if v is not None and str(v).strip() else None
    items = []
    for it in raw.get("line_items") or []:
        if not isinstance(it, dict):
            continue
        desc = it.get("description")
        items.append({
            "description": str(desc).strip() if desc is not None and str(desc).strip() else None,
            "quantity": parse_amount(it.get("quantity")),
            "unit_price": parse_amount(it.get("unit_price")),
            "amount": parse_amount(it.get("amount")),
        })
    out["line_items"] = items
    return out
