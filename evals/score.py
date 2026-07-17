"""Field-level scoring of an extraction against ground truth.

Rules are deliberately strict and mechanical so the headline accuracy is honest,
not massaged:
  - text (vendor, invoice_no): case-insensitive exact match after collapsing
    whitespace. No fuzzy credit — a scan that reads "Vesta1" is wrong.
  - date, currency: exact match.
  - amounts (subtotal, tax, total): equal within ±0.01.
  - line_items: rows are matched to ground truth, then EVERY attribute is scored —
    description (token recall), quantity, unit_price, amount. Scoring only the
    amount column would hide the hardest part of table extraction (reading rows,
    quantities and unit prices), so all four are measured and reported separately.
A field where truth is null and prediction is null counts as correct (the model
was right to leave it empty). Truth null / pred non-null is a miss.
"""

import re

SCALAR_FIELDS = ["vendor", "date", "invoice_no", "subtotal", "tax", "total", "currency"]
NUMERIC_FIELDS = {"subtotal", "tax", "total"}
ALL_FIELDS = SCALAR_FIELDS + ["line_items"]
LINE_ATTRS = ["description", "quantity", "unit_price", "amount"]


def _norm_text(v) -> str | None:
    if v is None:
        return None
    return re.sub(r"\s+", " ", str(v)).strip().lower() or None


def _num(v) -> float | None:
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _num_close(a, b) -> bool:
    na, nb = _num(a), _num(b)
    if na is None and nb is None:
        return True
    if na is None or nb is None:
        return False
    return abs(na - nb) <= 0.011


def _match_scalar(field: str, truth, pred) -> bool:
    if field in NUMERIC_FIELDS:
        return _num_close(truth, pred)
    if field == "invoice_no":
        t = re.sub(r"[\s\-]", "", str(truth).lower()) if truth is not None else None
        p = re.sub(r"[\s\-]", "", str(pred).lower()) if pred is not None else None
        return t == p
    return _norm_text(truth) == _norm_text(pred)


def _desc_recall(truth_desc, pred_desc) -> float:
    """Fraction of ground-truth description tokens present in the prediction.
    Partial credit, so an OCR slip on one word doesn't zero a whole row."""
    t_tokens = set(re.findall(r"[a-z0-9]+", str(truth_desc or "").lower()))
    p_tokens = set(re.findall(r"[a-z0-9]+", str(pred_desc or "").lower()))
    if not t_tokens:
        return 1.0 if not p_tokens else 0.0
    return len(t_tokens & p_tokens) / len(t_tokens)


def _item_pair_score(ti: dict, pi: dict) -> tuple[float, dict]:
    detail = {}
    detail["description"] = _desc_recall(ti.get("description"), pi.get("description"))
    for k in ("quantity", "unit_price", "amount"):
        if ti.get(k) is None:
            detail[k] = None  # not present in ground truth -> not scored
        else:
            detail[k] = 1.0 if _num_close(ti.get(k), pi.get(k)) else 0.0
    scored = [v for v in detail.values() if v is not None]
    return (sum(scored) / len(scored) if scored else 1.0), detail


def _match_line_items(truth_items: list, pred_items: list) -> tuple[float, dict]:
    """Greedily match each truth row to its best predicted row, then average the
    per-row attribute scores. Extra predicted rows dilute the denominator so
    hallucinated line items are penalized. Returns (composite, attr_breakdown)."""
    t = truth_items or []
    p = list(pred_items or [])
    empty_detail = {a: [] for a in LINE_ATTRS}
    if not t and not p:
        return 1.0, empty_detail
    if not t or not p:
        return 0.0, empty_detail

    remaining = list(range(len(p)))
    per_row = []
    attr_acc = {a: [] for a in LINE_ATTRS}
    for ti in t:
        best_i, best_s, best_d = None, -1.0, None
        for i in remaining:
            s, d = _item_pair_score(ti, p[i])
            if s > best_s:
                best_i, best_s, best_d = i, s, d
        if best_i is not None:
            remaining.remove(best_i)
            per_row.append(best_s)
            for a in LINE_ATTRS:
                if best_d[a] is not None:
                    attr_acc[a].append(best_d[a])
        else:
            per_row.append(0.0)

    n = max(len(t), len(p))
    composite = sum(per_row) / n
    return composite, attr_acc


def score_document(truth: dict, pred: dict) -> dict:
    """Return per-field correctness, a doc-level field-accuracy fraction, and a
    line-item attribute breakdown."""
    fields: dict[str, float] = {}
    for f in SCALAR_FIELDS:
        fields[f] = 1.0 if _match_scalar(f, truth.get(f), pred.get(f)) else 0.0
    li_score, li_detail = _match_line_items(truth.get("line_items"), pred.get("line_items"))
    fields["line_items"] = li_score

    field_acc = sum(fields.values()) / len(fields)
    all_correct = all(v == 1.0 for v in fields.values())

    # "Material" = the fields you'd actually post to a ledger: who, when, how much,
    # in what currency, and the line amounts. A slightly-off line-item DESCRIPTION
    # (an OCR token) is not a posting error, so it doesn't count here. This is the
    # metric that means "safe to auto-accept without a human".
    amounts_ok = all(v == 1.0 for v in (li_detail.get("amount") or []))
    material_correct = (
        all(fields[f] == 1.0 for f in ("vendor", "date", "total", "currency"))
        and fields["subtotal"] == 1.0
        and fields["tax"] == 1.0
        and amounts_ok
    )
    return {
        "fields": fields,
        "field_accuracy": field_acc,
        "all_correct": all_correct,
        "material_correct": material_correct,
        "line_item_attrs": li_detail,
    }
