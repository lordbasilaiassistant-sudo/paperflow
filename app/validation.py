"""Deterministic checks on a normalized extraction. These are ground truth the
LLM can't fake: arithmetic either adds up or it doesn't."""

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
        # Line items should reconcile against subtotal when present, else against total.
        if subtotal is not None:
            if not _close(items_sum, subtotal):
                issue("line_items", "sum_mismatch",
                      f"Line items sum to {items_sum:.2f} but subtotal is {subtotal:.2f}")
        elif total is not None:
            expected = round(total - (tax or 0), 2)
            if not _close(items_sum, expected):
                issue("line_items", "sum_mismatch",
                      f"Line items sum to {items_sum:.2f} but total minus tax is {expected:.2f}")
    elif items:
        issue("line_items", "missing_amounts", "Some line items have no amount", "warning")

    if subtotal is not None and total is not None:
        if not _close(round(subtotal + (tax or 0), 2), total):
            issue("total", "total_mismatch",
                  f"subtotal ({subtotal:.2f}) + tax ({(tax or 0):.2f}) != total ({total:.2f})")

    for it in items:
        q, up, amt = it.get("quantity"), it.get("unit_price"), it.get("amount")
        if q is not None and up is not None and amt is not None and not _close(round(q * up, 2), amt):
            issue("line_items", "item_math",
                  f"{q} x {up:.2f} != {amt:.2f} for '{(it.get('description') or '?')[:40]}'", "warning")

    return issues
