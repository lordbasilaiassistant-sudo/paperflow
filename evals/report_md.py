"""Render the eval report as Markdown from results/latest.json.

    python -m evals.report_md

Used to fill the README's results table directly from a real run, so the numbers
in the docs are the numbers the harness produced — never hand-typed.
"""

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

RESULTS = Path(__file__).parent / "results" / "latest.json"


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def main() -> int:
    if not RESULTS.exists():
        print("No results/latest.json — run `python -m evals.run` first.", file=sys.stderr)
        return 1
    rep = json.loads(RESULTS.read_text(encoding="utf-8"))

    out: list[str] = []
    r = rep["routing"]
    c = rep["cost"]

    out.append(f"**{rep['n_ok']} documents** · **{_pct(rep['overall_field_accuracy'])} field accuracy** · "
               f"**{_pct(r['auto_accept_rate'])}** auto-accepted at **{_pct(r['auto_accept_accuracy'])}** "
               f"accuracy · **{r['material_false_accepts']}** material false accepts "
               f"({_pct(r['material_false_accept_rate'])} of auto-accepted)\n")

    out.append("| Metric | Value |")
    out.append("|---|---|")
    out.append(f"| Documents scored | {rep['n_ok']}"
               + (f" ({rep['n_failed']} pipeline failures)" if rep.get("n_failed") else "") + " |")
    out.append(f"| Overall field accuracy | {_pct(rep['overall_field_accuracy'])} |")
    out.append(f"| Docs fully correct (every field exact) | {rep['docs_fully_correct']}/{rep['n_ok']} "
               f"({_pct(rep['docs_fully_correct'] / rep['n_ok'])}) |")
    out.append(f"| Auto-accepted (no human) | {r['auto_accepted']} ({_pct(r['auto_accept_rate'])}), "
               f"at {_pct(r['auto_accept_accuracy'])} field accuracy |")
    out.append(f"| Sent to review | {r['needs_review']} ({_pct(1 - r['auto_accept_rate'])}), "
               f"at {_pct(r['review_accuracy'])} field accuracy |")
    out.append(f"| **Material false accepts** (auto-accepted with a wrong vendor/date/amount/currency) | "
               f"**{r['material_false_accepts']}** ({_pct(r['material_false_accept_rate'])} of auto-accepted) |")
    out.append(f"| False accepts incl. cosmetic (any field, e.g. an OCR-slipped description token) | "
               f"{r['false_accepts']} ({_pct(r['false_accept_rate'])} of auto-accepted) |")
    out.append(f"| Tokens / doc | {c['tokens_per_doc']:.0f} |")
    out.append(f"| Cost / doc | ${c['cost_per_doc_usd']:.5f}"
               + (" (model priced at $0, free tier)" if c["cost_per_doc_usd"] == 0 else "") + " |")
    out.append("")

    out.append("**Field accuracy by document category**\n")
    out.append("| Category | n | Field accuracy | Fully correct | Auto-accept rate |")
    out.append("|---|---|---|---|---|")
    for cat, cc in rep["per_category"].items():
        out.append(f"| {cat} | {cc['n']} | {_pct(cc['field_accuracy'])} | "
                   f"{cc['fully_correct']}/{cc['n']} | {_pct(cc['auto_accept_rate'])} |")
    out.append("")

    out.append("**Per-field accuracy**\n")
    out.append("| Field | Accuracy |")
    out.append("|---|---|")
    order = ["vendor", "date", "invoice_no", "subtotal", "tax", "total", "currency", "line_items"]
    for f in order:
        if f in rep["per_field"]:
            out.append(f"| {f} | {_pct(rep['per_field'][f])} |")
    if rep.get("line_item_attrs"):
        out.append("")
        out.append("Line-item attributes (matched rows): "
                   + ", ".join(f"{a} {_pct(rep['line_item_attrs'][a])}"
                               for a in ["description", "quantity", "unit_price", "amount"]
                               if a in rep["line_item_attrs"]) + ".")

    if rep.get("threshold_sweep"):
        out.append("")
        out.append("**Auto-accept threshold tradeoff** — raising the confidence bar trades automation "
                   "for fewer false accepts. There is no free 100%: the floor is genuine ambiguity "
                   "(a `$` that could be USD or CAD) the model cannot resolve from the page.\n")
        out.append("| Threshold | Auto-accepted | Material false accepts |")
        out.append("|---|---|---|")
        for s in rep["threshold_sweep"]:
            out.append(f"| {s['threshold']:.2f} | {s['auto_accepted']} ({_pct(s['auto_accept_rate'])}) | "
                       f"{s['material_false_accepts']} ({_pct(s['material_false_accept_rate'])}) |")

    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
