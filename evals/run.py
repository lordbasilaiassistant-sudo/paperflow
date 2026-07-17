"""Run the extraction pipeline over the fixture corpus and print an honest report.

    python -m evals.run                 # full corpus
    python -m evals.run --subset 10     # first 10 fixtures (used by CI)
    python -m evals.run --json out.json # also dump machine-readable results

Reported metrics (all measured, none hand-tuned):
  - field-level accuracy overall and per field
  - accuracy per document category (clean / scan / photo / multipage / edge)
  - routing: % auto-accepted vs % sent to review
  - routing quality: accuracy of auto-accepted docs vs routed docs, and the
    false-accept rate (docs auto-accepted whose extraction was not fully correct)
  - cost/doc: tokens and USD
"""

import argparse
import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app import pipeline
from evals import generate, score

sys.stdout.reconfigure(encoding="utf-8")

FIXTURES_DIR = Path(__file__).parent / "fixtures"
RESULTS_DIR = Path(__file__).parent / "results"


def _run_one(rec: dict) -> dict:
    path = FIXTURES_DIR / rec["file"]
    t0 = time.time()
    try:
        result = pipeline.process(path)
        sc = score.score_document(rec["truth"], result.extraction)
        return {
            "id": rec["id"], "category": rec["category"], "ok": True,
            "route": result.route, "doc_confidence": result.doc_confidence,
            "field_accuracy": sc["field_accuracy"], "all_correct": sc["all_correct"],
            "material_correct": sc["material_correct"],
            "fields": sc["fields"], "line_item_attrs": sc["line_item_attrs"],
            "source_type": result.source_type,
            "prompt_tokens": result.prompt_tokens, "completion_tokens": result.completion_tokens,
            "cost_usd": result.cost_usd, "seconds": round(time.time() - t0, 2),
        }
    except Exception as e:
        return {"id": rec["id"], "category": rec["category"], "ok": False,
                "error": f"{type(e).__name__}: {e}", "seconds": round(time.time() - t0, 2)}


def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:.1f}%" if d else "—"


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def build_report(results: list[dict]) -> dict:
    ok = [r for r in results if r.get("ok")]
    failed = [r for r in results if not r.get("ok")]
    n = len(ok)

    per_field: dict[str, list[float]] = defaultdict(list)
    for r in ok:
        for f, v in r["fields"].items():
            per_field[f].append(v)

    li_attrs: dict[str, list[float]] = defaultdict(list)
    for r in ok:
        for a, vals in (r.get("line_item_attrs") or {}).items():
            li_attrs[a].extend(vals)

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in ok:
        by_cat[r["category"]].append(r)

    auto = [r for r in ok if r["route"] == "auto_accept"]
    review = [r for r in ok if r["route"] == "needs_review"]
    false_accepts = [r for r in auto if not r["all_correct"]]
    material_false_accepts = [r for r in auto if not r.get("material_correct", r["all_correct"])]
    caught = [r for r in review if not r["all_correct"]]  # correctly sent to review

    total_tokens = sum(r["prompt_tokens"] + r["completion_tokens"] for r in ok)
    total_cost = sum(r["cost_usd"] for r in ok)

    # Threshold tradeoff: raising the auto-accept confidence bar moves borderline
    # docs from auto-accept to review — fewer false accepts, less automation. Only
    # docs that already cleared the other gates (no error, required fields grounded)
    # are eligible, so this sweeps the confidence dimension of the same routing.
    eligible = [r for r in ok if r["route"] == "auto_accept"]
    sweep = []
    for t in (0.80, 0.85, 0.90, 0.95):
        a = [r for r in eligible if r["doc_confidence"] >= t]
        mfa = [r for r in a if not r.get("material_correct", r["all_correct"])]
        sweep.append({
            "threshold": t, "auto_accepted": len(a),
            "auto_accept_rate": len(a) / n if n else 0.0,
            "material_false_accepts": len(mfa),
            "material_false_accept_rate": len(mfa) / len(a) if a else 0.0,
        })

    return {
        "n_total": len(results), "n_ok": n, "n_failed": len(failed),
        "failed": [{"id": r["id"], "error": r.get("error")} for r in failed],
        "overall_field_accuracy": _mean([r["field_accuracy"] for r in ok]),
        "docs_fully_correct": sum(1 for r in ok if r["all_correct"]),
        "per_field": {f: _mean(v) for f, v in per_field.items()},
        "line_item_attrs": {a: _mean(v) for a, v in li_attrs.items() if v},
        "per_category": {
            cat: {
                "n": len(rs),
                "field_accuracy": _mean([r["field_accuracy"] for r in rs]),
                "fully_correct": sum(1 for r in rs if r["all_correct"]),
                "auto_accept_rate": _mean([1.0 if r["route"] == "auto_accept" else 0.0 for r in rs]),
            }
            for cat, rs in sorted(by_cat.items())
        },
        "routing": {
            "auto_accepted": len(auto), "needs_review": len(review),
            "auto_accept_rate": _mean([1.0 if r["route"] == "auto_accept" else 0.0 for r in ok]),
            "auto_accept_accuracy": _mean([r["field_accuracy"] for r in auto]),
            "review_accuracy": _mean([r["field_accuracy"] for r in review]),
            "false_accepts": len(false_accepts),
            "false_accept_rate": len(false_accepts) / len(auto) if auto else 0.0,
            "false_accept_ids": [r["id"] for r in false_accepts],
            "material_false_accepts": len(material_false_accepts),
            "material_false_accept_rate": len(material_false_accepts) / len(auto) if auto else 0.0,
            "material_false_accept_ids": [r["id"] for r in material_false_accepts],
            "review_correctly_flagged": len(caught),
        },
        "threshold_sweep": sweep,
        "cost": {
            "total_tokens": total_tokens,
            "tokens_per_doc": total_tokens / n if n else 0,
            "total_cost_usd": total_cost,
            "cost_per_doc_usd": total_cost / n if n else 0,
        },
    }


def print_report(rep: dict) -> None:
    line = "─" * 66
    print("\n" + line)
    print("  paperflow — extraction eval")
    print(line)
    print(f"  Documents:        {rep['n_ok']} scored"
          + (f"  ({rep['n_failed']} pipeline failures)" if rep['n_failed'] else ""))
    print(f"  Field accuracy:   {rep['overall_field_accuracy']*100:.1f}%  (micro-avg over 8 fields)")
    print(f"  Fully correct:    {rep['docs_fully_correct']}/{rep['n_ok']}"
          f"  ({_pct(rep['docs_fully_correct'], rep['n_ok'])} of docs, every field right)")

    print("\n  Per field")
    order = ["vendor", "date", "invoice_no", "subtotal", "tax", "total", "currency", "line_items"]
    for f in order:
        if f in rep["per_field"]:
            print(f"    {f:12s} {rep['per_field'][f]*100:5.1f}%")

    if rep.get("line_item_attrs"):
        print("\n  Line-item attributes (matched rows)")
        for a in ["description", "quantity", "unit_price", "amount"]:
            if a in rep["line_item_attrs"]:
                print(f"    {a:12s} {rep['line_item_attrs'][a]*100:5.1f}%")

    print("\n  Per category            n   field-acc   fully-correct   auto-accept")
    for cat, c in rep["per_category"].items():
        print(f"    {cat:14s} {c['n']:5d}   {c['field_accuracy']*100:6.1f}%   "
              f"{_pct(c['fully_correct'], c['n']):>10s}     {c['auto_accept_rate']*100:5.1f}%")

    r = rep["routing"]
    print("\n  Routing")
    print(f"    auto-accepted:  {r['auto_accepted']}  ({r['auto_accept_rate']*100:.1f}%)   "
          f"field-acc {r['auto_accept_accuracy']*100:.1f}%")
    print(f"    needs-review:   {r['needs_review']}  ({(1-r['auto_accept_rate'])*100:.1f}%)   "
          f"field-acc {r['review_accuracy']*100:.1f}%")
    print(f"    false accepts:  {r['false_accepts']}  "
          f"({r['false_accept_rate']*100:.1f}% of auto-accepted not 100% correct, incl. cosmetic)")
    print(f"    MATERIAL false: {r['material_false_accepts']}  "
          f"({r['material_false_accept_rate']*100:.1f}% auto-accepted with a wrong "
          f"vendor/date/amount/currency)")
    if r["material_false_accept_ids"]:
        print(f"                    ids: {', '.join(r['material_false_accept_ids'])}")

    if rep.get("threshold_sweep"):
        print("\n  Auto-accept threshold tradeoff")
        print("    thresh   auto-accepted   material false-accepts")
        for s in rep["threshold_sweep"]:
            print(f"    {s['threshold']:.2f}     {s['auto_accepted']:3d} ({s['auto_accept_rate']*100:4.1f}%)"
                  f"      {s['material_false_accepts']:2d} ({s['material_false_accept_rate']*100:4.1f}%)")

    c = rep["cost"]
    print("\n  Cost")
    print(f"    tokens/doc:     {c['tokens_per_doc']:.0f}")
    print(f"    cost/doc:       ${c['cost_per_doc_usd']:.5f}"
          + ("   (model priced at $0 — free tier)" if c["cost_per_doc_usd"] == 0 else ""))
    print(line + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subset", type=int, default=None, help="Only run the first N fixtures")
    ap.add_argument("--workers", type=int, default=2,
                    help="Concurrent pipeline runs. Keep low on free LLM tiers (rate limits).")
    ap.add_argument("--json", type=str, default=None, help="Write full results JSON to this path")
    args = ap.parse_args()

    manifest = generate.load_manifest()
    if not manifest:
        print("No fixtures found. Run:  python -m evals.generate", file=sys.stderr)
        return 2
    if args.subset:
        manifest = manifest[: args.subset]

    print(f"Running pipeline over {len(manifest)} fixtures ({args.workers} workers)…")
    results: list[dict] = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(_run_one, rec): rec for rec in manifest}
        done = 0
        for fut in as_completed(futures):
            results.append(fut.result())
            done += 1
            if done % 10 == 0 or done == len(manifest):
                print(f"  {done}/{len(manifest)}")
    results.sort(key=lambda r: r["id"])

    rep = build_report(results)
    rep["wall_seconds"] = round(time.time() - t0, 1)
    print_report(rep)
    print(f"  wall time: {rep['wall_seconds']}s\n")

    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "latest.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps({"report": rep, "results": results}, indent=2), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
