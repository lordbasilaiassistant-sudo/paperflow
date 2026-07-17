"""Deterministic checks on a normalized extraction.

These check INTERNAL consistency — the arithmetic either agrees with itself or it
doesn't. That is genuine evidence, but not proof of correctness: an invoice with a
discount, shipping, multiple tax rates, or a tax-inclusive total legitimately does
NOT satisfy subtotal + tax == total. So arithmetic disagreements are raised as
*warnings* (which route the document to human review) rather than *errors* (which
assert the extraction is wrong). Only truly required-field problems are errors.
"""

import re

from app.models import REQUIRED_FIELDS

TOLERANCE = 0.011  # ±0.01 with float slack


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= TOLERANCE


def validate(ex: dict) -> list[dict]:
    issues: list[dict] = []

    def issue(fieldname: str, code: str, message: str, severity: str = "error"):
        issues.append({"field": fieldname, "code": code, "message": message, "severity": severity})

    for f in REQUIRED_FIELDS:
        if ex.get(f) in (None, ""):
            issue(f, "missing_required", f"Required field '{f}' is missing")

    date = ex.get("date")
    if date is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(date)):
        issue("date", "bad_date", f"Date '{date}' did not normalize to ISO YYYY-MM-DD")

    currency = ex.get("currency")
    if currency is not None and not re.fullmatch(r"[A-Z]{3}", str(currency)):
        issue("currency", "bad_currency", f"Currency '{currency}' is not a 3-letter code", "warning")

    items = ex.get("line_items") or []
    subtotal, tax, total = ex.get("subtotal"), ex.get("tax"), ex.get("total")

    item_amounts = [it.get("amount") for it in items]
    if items and all(a is not None for a in item_amounts):
        items_sum = round(sum(item_amounts), 2)
        # Line items reconcile against subtotal when present. A mismatch is a
        # warning: it may be a real discount/shipping row shown separately, or a
        # genuine extraction error — either way a human should look.
        if subtotal is not None:
            if not _close(items_sum, subtotal):
                issue("line_items", "sum_mismatch",
                      f"Line items sum to {items_sum:.2f} but subtotal is {subtotal:.2f} "
                      f"(discount/shipping row, or a misread — review)", "warning")
        elif total is not None and tax is not None:
            expected = round(total - tax, 2)
            if not _close(items_sum, expected):
                issue("line_items", "sum_mismatch",
                      f"Line items sum to {items_sum:.2f} but total minus tax is {expected:.2f}", "warning")
    elif items:
        issue("line_items", "missing_amounts", "Some line items have no amount", "warning")

    # subtotal + tax == total only checked when BOTH subtotal and tax are known.
    # Treating a missing tax as 0 would let subtotal == total "reconcile" falsely.
    if subtotal is not None and tax is not None and total is not None:
        if not _close(round(subtotal + tax, 2), total):
            issue("total", "total_mismatch",
                  f"subtotal ({subtotal:.2f}) + tax ({tax:.2f}) != total ({total:.2f}) "
                  f"(extra charges, tax-inclusive total, or a misread — review)", "warning")

    for it in items:
        q, up, amt = it.get("quantity"), it.get("unit_price"), it.get("amount")
        if q is not None and up is not None and amt is not None and not _close(round(q * up, 2), amt):
            issue("line_items", "item_math",
                  f"{q} x {up:.2f} != {amt:.2f} for '{(it.get('description') or '?')[:40]}'", "warning")

    return issues
