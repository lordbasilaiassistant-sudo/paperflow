"""Confidence scoring and routing.

A flash model's self-reported confidence is a weak signal — these models are
cheerfully overconfident, and (the failure that matters most) a model can
hallucinate a set of numbers that is internally consistent but absent from the
document. So the score never trusts self-confidence alone. It blends three signals:

  1. model self-confidence          — a weak prior
  2. SOURCE GROUNDING                — does the extracted value actually appear in
                                       the document text? A value the model is sure
                                       of but that is nowhere in the source is
                                       capped low. This is what stops a confident
                                       hallucination from being auto-accepted.
  3. arithmetic corroboration        — line items + subtotal/total reconciling is
                                       evidence the numbers agree with EACH OTHER.
                                       It only boosts financial fields that are ALSO
                                       grounded, and only for a non-trivial
                                       reconciliation (real line items, not a lone
                                       total equal to itself).

Auto-accept additionally GATES on the required fields (vendor, date, total) each
being present, grounded, and clearing a floor — a high average from boosted
financials can't carry a wrong vendor over the line.
"""

import re

from app import config
from app.models import REQUIRED_FIELDS, SCALAR_FIELDS

FIELD_WEIGHTS = {
    "total": 3.0, "date": 2.0, "vendor": 2.0, "line_items": 2.0,
    "subtotal": 1.0, "tax": 1.0, "invoice_no": 1.0, "currency": 1.0,
}

ERROR_CAP = 0.30
WARNING_CAP = 0.60
UNGROUNDED_CAP = 0.45          # value not found in source text -> likely a misread/hallucination
ARITHMETIC_BOOST = 0.90        # grounded + non-trivially reconciling financials
REQUIRED_ACCEPT_FLOOR = 0.70   # each required field must clear this to auto-accept
FINANCIAL_FIELDS = ("subtotal", "tax", "total", "line_items")
REQUIRED_FOR_ACCEPT = ("vendor", "date", "total")

MATH_ISSUE_CODES = {"sum_mismatch", "total_mismatch", "item_math", "missing_amounts"}


def _index_text(raw_text: str) -> tuple[str, str]:
    """Return (all digits concatenated, lowercased whitespace-collapsed text)."""
    return re.sub(r"\D", "", raw_text or ""), re.sub(r"\s+", " ", (raw_text or "").lower())


def _amount_grounded(value: float, text_digits: str) -> bool:
    v = abs(value)
    forms = {
        re.sub(r"\D", "", f"{v:.2f}"),   # 266.56 -> "26656"
        re.sub(r"\D", "", f"{v:g}"),     # 1234.0 -> "1234"; 266.56 -> "26656"
        str(int(round(v))),              # whole-number rendering
    }
    return any(f and f in text_digits for f in forms)


def _text_grounded(value: str, text_norm: str) -> bool:
    words = [w for w in re.findall(r"[a-z0-9]+", str(value).lower()) if len(w) >= 3]
    if not words:
        return True  # too short to verify — don't penalize
    hits = sum(1 for w in words if w in text_norm)
    return hits >= max(1, len(words) // 2)


def _is_grounded(field: str, value, text_digits: str, text_norm: str) -> bool:
    if field in ("subtotal", "tax", "total"):
        return _amount_grounded(float(value), text_digits)
    if field == "line_items":
        amounts = [it.get("amount") for it in (value or []) if it.get("amount") is not None]
        if not amounts:
            return False
        hit = sum(1 for a in amounts if _amount_grounded(float(a), text_digits))
        return hit >= max(1, len(amounts) // 2)
    if field in ("vendor", "invoice_no"):
        return _text_grounded(value, text_norm)
    return True  # currency/date aren't reliably substring-checkable


def _reconciles_nontrivially(extraction: dict, issues: list[dict]) -> bool:
    """True only when genuinely independent numbers agree — real line items plus a
    subtotal or total. A lone total equal to itself is not corroboration."""
    items = [it for it in (extraction.get("line_items") or []) if it.get("amount") is not None]
    independent = len(items) >= 1 and (
        extraction.get("subtotal") is not None or extraction.get("total") is not None
    )
    if not independent:
        return False
    return not any(i["code"] in MATH_ISSUE_CODES for i in issues)


def score(extraction: dict, model_confidence: dict, issues: list[dict], *,
          raw_text: str = "", parse_failed: bool = False) -> dict:
    """Return {"fields": {field: conf|None}, "doc": float, "route": ...}."""
    if parse_failed:
        return {"fields": dict.fromkeys(FIELD_WEIGHTS, 0.0), "doc": 0.0, "route": "needs_review"}

    text_digits, text_norm = _index_text(raw_text)
    have_text = bool(text_digits or text_norm)

    def clamp(v) -> float:
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.5

    fields: dict[str, float | None] = {}
    grounded: dict[str, bool] = {}
    for f in SCALAR_FIELDS + ["line_items"]:
        value = extraction.get(f)
        present = value not in (None, "", [])
        if not present:
            # Missing required -> 0. Missing optional -> None (excluded from the
            # doc score; a receipt with no invoice number shouldn't be penalized).
            fields[f] = 0.0 if f in REQUIRED_FIELDS else None
            continue
        conf = clamp(model_confidence.get(f, 0.5))
        # Without source text we can't verify grounding, so we don't enforce it
        # (treat as grounded) rather than penalize every field.
        g = _is_grounded(f, value, text_digits, text_norm) if have_text else True
        grounded[f] = g
        if have_text and not g:
            conf = min(conf, UNGROUNDED_CAP)
        fields[f] = conf

    if _reconciles_nontrivially(extraction, issues):
        for f in FINANCIAL_FIELDS:
            if fields.get(f) is not None and grounded.get(f, not have_text):
                fields[f] = max(fields[f], ARITHMETIC_BOOST)

    issue_fields = {(i["field"], i["severity"]) for i in issues}
    for f, conf in fields.items():
        if conf is None:
            continue
        if (f, "error") in issue_fields:
            fields[f] = min(conf, ERROR_CAP)
        elif (f, "warning") in issue_fields:
            fields[f] = min(conf, WARNING_CAP)

    scored = [(f, c) for f, c in fields.items() if c is not None]
    weight_sum = sum(FIELD_WEIGHTS[f] for f, _ in scored) or 1.0
    doc = sum(FIELD_WEIGHTS[f] * c for f, c in scored) / weight_sum

    has_error = any(i["severity"] == "error" for i in issues)
    required_ok = all(
        extraction.get(f) not in (None, "", [])
        and grounded.get(f, not have_text)
        and (fields.get(f) or 0.0) >= REQUIRED_ACCEPT_FLOOR
        for f in REQUIRED_FOR_ACCEPT
    )
    route = "auto_accept" if (doc >= config.ROUTE_THRESHOLD and not has_error and required_ok) else "needs_review"
    return {"fields": fields, "doc": round(doc, 4), "route": route}
