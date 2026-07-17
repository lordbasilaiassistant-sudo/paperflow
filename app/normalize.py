"""Deterministic cleanup of raw LLM output before validation.

The model returns what it saw; this module makes it comparable: amounts become
floats, dates become ISO, currency becomes a 3-letter code. Anything that can't
be normalized is left as-is so validation can flag it instead of silently
dropping data.
"""

import re
from datetime import datetime

CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR"}

# Currencies whose home locales write the day first (DD/MM). Used only to break
# genuinely ambiguous slash dates (both parts <= 12); unambiguous dates parse the
# same either way because strptime rejects an out-of-range month.
DAY_FIRST_CURRENCIES = {"EUR", "GBP", "AUD", "NZD", "INR", "CHF", "SEK", "NOK", "DKK"}

# Year-first is unambiguous and always tried first.
_ISO_FORMATS = ["%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"]
_MONTH_FIRST = ["%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y"]
_DAY_FIRST = ["%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d.%m.%Y"]
_TEXT_FORMATS = [
    "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%d-%b-%Y", "%b %d %Y",
    "%b %d '%y", "%B %d '%y", "%d %b '%y",  # abbreviated month, apostrophe 2-digit year
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
    negative = negative or s.startswith("-")
    s = s.lstrip("-")
    if "," in s and "." in s:
        # Both separators present: the one that appears LAST is the decimal point.
        # 1.234,56 (European) -> 1234.56 ; 1,234.56 (US) -> 1234.56
        if s.rindex(",") > s.rindex("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = _resolve_single_separator(s, ",")
    elif "." in s:
        s = _resolve_single_separator(s, ".")
    try:
        v = float(s)
    except ValueError:
        return None
    return round(-v if negative else v, 2)


def _resolve_single_separator(s: str, sep: str) -> str:
    """Decide whether a lone separator is a decimal point or a thousands mark.

    Rules tuned for invoice amounts, where 3+ decimal places are effectively
    never used:
      - separator appears more than once  -> thousands ("1.000.000" -> 1000000)
      - one separator, exactly 3 digits after -> thousands ("1.500" -> 1500)
      - one separator, 1-2 digits after      -> decimal   ("1,5" -> 1.5, "12.50" -> 12.50)
    """
    parts = s.split(sep)
    if len(parts) > 2:
        return s.replace(sep, "")
    whole, frac = parts[0], parts[1]
    if frac == "":
        return whole
    if len(frac) == 3 and whole != "":
        return whole + frac  # thousands grouping
    return whole + "." + frac  # decimal


def parse_date(value, *, day_first: bool = False) -> str | None:
    """Return ISO YYYY-MM-DD, or None if the value can't be parsed.

    day_first only affects genuinely ambiguous slash dates (e.g. 05/06/2024);
    an unambiguous date like 13/05/2024 parses to the same day regardless.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", s)
    slash = (_DAY_FIRST + _MONTH_FIRST) if day_first else (_MONTH_FIRST + _DAY_FIRST)
    for fmt in _ISO_FORMATS + slash + _TEXT_FORMATS:
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
    currency = parse_currency(raw.get("currency"))
    out["currency"] = currency
    day_first = currency in DAY_FIRST_CURRENCIES
    out["date"] = parse_date(raw.get("date"), day_first=day_first) or (
        str(raw.get("date")).strip() if raw.get("date") else None
    )
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
