"""Confidence scoring and routing.

Model self-confidence is a weak signal on its own — flash models are cheerfully
overconfident. So the score blends it with evidence the model can't fake:
- arithmetic agreement (line items + tax reconciling to the total is three
  independent numbers agreeing — strong evidence the whole read is right)
- validation failures (hard caps: an error on a field caps its confidence)
A document is auto-accepted only when the blended score clears the threshold
AND no error-severity validation issue exists. Errors always route to review.
"""

from app import config
from app.models import REQUIRED_FIELDS, SCALAR_FIELDS

FIELD_WEIGHTS = {
    "total": 3.0, "date": 2.0, "vendor": 2.0, "line_items": 2.0,
    "subtotal": 1.0, "tax": 1.0, "invoice_no": 1.0, "currency": 1.0,
}

ERROR_CAP = 0.30
WARNING_CAP = 0.60
ARITHMETIC_BOOST = 0.97
FINANCIAL_FIELDS = ("subtotal", "tax", "total", "line_items")


def score(extraction: dict, model_confidence: dict, issues: list[dict], *, parse_failed: bool = False) -> dict:
    """Return {"fields": {field: conf|None}, "doc": float, "route": "auto_accept"|"needs_review"}."""
    if parse_failed:
        return {"fields": dict.fromkeys(FIELD_WEIGHTS, 0.0), "doc": 0.0, "route": "needs_review"}

    def clamp(v) -> float:
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.5

    fields: dict[str, float | None] = {}
    for f in SCALAR_FIELDS + ["line_items"]:
        value = extraction.get(f)
        present = value not in (None, "", [])
        if not present:
            # Missing required -> 0. Missing optional -> None (excluded from doc score):
            # a receipt with no invoice number shouldn't be dragged down for honesty.
            fields[f] = 0.0 if f in REQUIRED_FIELDS else None
        else:
            fields[f] = clamp(model_confidence.get(f, 0.5))

    issue_fields = {(i["field"], i["severity"]) for i in issues}

    # Arithmetic agreement: no sum/total mismatches and the numbers exist to check.
    has_math = extraction.get("total") is not None and (
        extraction.get("line_items") or extraction.get("subtotal") is not None
    )
    math_codes = {"sum_mismatch", "total_mismatch", "item_math", "missing_amounts"}
    math_clean = has_math and not any(i["code"] in math_codes for i in issues)
    if math_clean:
        for f in FINANCIAL_FIELDS:
            if fields.get(f) is not None:
                fields[f] = max(fields[f], ARITHMETIC_BOOST)

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
    route = "auto_accept" if (doc >= config.ROUTE_THRESHOLD and not has_error) else "needs_review"
    return {"fields": fields, "doc": round(doc, 4), "route": route}
