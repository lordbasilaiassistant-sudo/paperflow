"""Generate the fixture corpus deterministically.

    python -m evals.generate            # ~106 docs into evals/fixtures/
    python -m evals.generate --n 20     # smaller set (still deterministic prefix)

Every fixture is seeded from a master seed + its index, so the corpus is
byte-reproducible on any machine and CI can regenerate it instead of storing
binaries. Ground truth is written to evals/fixtures/ground_truth.jsonl.
"""

import argparse
import json
import random
import shutil
import sys
from pathlib import Path

from evals import gen_data, render

sys.stdout.reconfigure(encoding="utf-8")

FIXTURES_DIR = Path(__file__).parent / "fixtures"
MASTER_SEED = 20260717

LAYOUTS = ["classic", "modern", "receipt"]
# "compact" (Jan 5 '24) is deliberately NOT handled by the normalizer, so date
# accuracy reflects real capability rather than the generator matching the parser.
DATE_STYLES = ["iso", "us", "long", "dots", "compact"]

# (kind, count, builder-kwargs, degradation) — degradation applied to the rendered PDF.
# Total across the plan is >100. Order matters only for deterministic prefixes.
PLAN = [
    ("clean_pdf", 30, {}, None),
    ("scan", 24, {}, "scan"),
    ("photo", 22, {}, "photo"),
    ("multipage", 12, {"n_items": 14}, None),
    # Legitimately NON-reconciling: discount + shipping shown separately, so
    # subtotal + tax != total. Stresses the routing path most likely to false-accept.
    ("edge_adjustments", 6, {"edge": "adjustments"}, None),
    # Currency printed as a bare "$" while the true currency is CAD — genuine ambiguity.
    ("edge_currency_ambiguous", 4, {"currency": "CAD"}, None),
    ("edge_negative_total", 4, {"edge": "negative_total", "n_items": 2}, None),
    ("edge_missing_invoice_no", 3, {"edge": "missing_invoice_no"}, None),
    ("edge_missing_tax", 3, {"edge": "missing_tax"}, None),
    ("edge_no_line_prices", 4, {"edge": "no_line_prices"}, None),
]

# A couple of edge cases also degraded, so "hard + weird" is represented.
PLAN += [
    ("edge_negative_total", 2, {"edge": "negative_total", "n_items": 2}, "photo"),
    ("edge_no_line_prices", 2, {"edge": "no_line_prices"}, "scan"),
    ("edge_adjustments", 2, {"edge": "adjustments"}, "scan"),
]


def _strip_meta(truth: dict) -> dict:
    return {k: v for k, v in truth.items() if k != "_meta"}


def generate(n_limit: int | None = None) -> list[dict]:
    if FIXTURES_DIR.exists():
        shutil.rmtree(FIXTURES_DIR)
    FIXTURES_DIR.mkdir(parents=True)

    records: list[dict] = []
    idx = 0
    for kind, count, kwargs, degrade in _expanded_plan():
        for _ in range(count):
            if n_limit is not None and idx >= n_limit:
                _write_manifest(records)
                return records
            rng = random.Random(MASTER_SEED + idx * 131)
            layout = "receipt" if kwargs.get("edge") == "no_line_prices" else rng.choice(LAYOUTS)
            date_style = rng.choice(DATE_STYLES)
            truth = gen_data.make_invoice(rng, **kwargs)

            fid = f"{idx:03d}_{kind}"
            pdf_path = FIXTURES_DIR / f"{fid}.pdf"
            render.render_pdf(truth, pdf_path, layout=layout, date_style=date_style)

            if degrade is None:
                final_path = pdf_path
            else:
                img = render.pdf_to_image(pdf_path)
                if degrade == "scan":
                    out = FIXTURES_DIR / f"{fid}.png"
                    render.degrade_scan(img, rng).save(out)
                else:  # photo
                    out = FIXTURES_DIR / f"{fid}.jpg"
                    render.degrade_photo(img, rng).save(out)
                pdf_path.unlink()
                final_path = out

            records.append({
                "id": fid,
                "kind": kind,
                "category": _category(kind, degrade),
                "file": final_path.name,
                "truth": _strip_meta(truth),
            })
            idx += 1

    _write_manifest(records)
    return records


def _expanded_plan():
    return PLAN


def _category(kind: str, degrade: str | None) -> str:
    if degrade == "scan":
        return "scan"
    if degrade == "photo":
        return "photo"
    if kind == "multipage":
        return "multipage"
    if kind.startswith("edge"):
        return "edge"
    return "clean_pdf"


def _write_manifest(records: list[dict]) -> None:
    with open(FIXTURES_DIR / "ground_truth.jsonl", "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def load_manifest() -> list[dict]:
    path = FIXTURES_DIR / "ground_truth.jsonl"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=None, help="Limit number of fixtures")
    args = ap.parse_args()
    recs = generate(args.n)
    from collections import Counter

    cats = Counter(r["category"] for r in recs)
    print(f"Generated {len(recs)} fixtures into {FIXTURES_DIR}")
    for cat, c in sorted(cats.items()):
        print(f"  {cat:12s} {c}")
