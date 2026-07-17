"""Deterministic synthetic invoice/receipt data. Seeded so `python -m evals.generate`
produces byte-identical ground truth on any machine — CI regenerates fixtures
instead of committing binaries."""

import random
from dataclasses import dataclass

VENDORS = [
    ("Northwind Traders LLC", "482 Commerce Blvd, Portland, OR 97201"),
    ("Blue Harbor Supply Co.", "1120 Dockside Ave, Seattle, WA 98101"),
    ("Cedar & Pine Office Goods", "77 Main St, Burlington, VT 05401"),
    ("Apex Industrial Parts", "9 Factory Row, Cleveland, OH 44113"),
    ("Lakeside Catering Group", "310 Shoreline Dr, Madison, WI 53703"),
    ("Summit IT Services", "4501 Peak Plaza, Denver, CO 80202"),
    ("Greenfield Landscaping", "22 Meadow Ln, Ithaca, NY 14850"),
    ("Métro Papeterie SARL", "18 Rue de la Gare, 69002 Lyon"),
    ("Küster Werkzeuge GmbH", "Hauptstraße 44, 50667 Köln"),
    ("Sakura Print Studio", "2-14-6 Ginza, Chuo-ku, Tokyo"),
    ("Harbor Freight & Salvage", "600 Wharf St, New Bedford, MA 02740"),
    ("Vestal Auto Repair", "408 Front St, Vestal, NY 13850"),
]

PRODUCTS = [
    ("A4 copy paper, 500 sheets", 4.99, 12.50),
    ("Toner cartridge, black", 39.00, 89.00),
    ("USB-C dock", 45.00, 129.00),
    ("Standing desk mat", 25.00, 65.00),
    ("Catering — lunch buffet per head", 12.00, 28.00),
    ("On-site support (hourly)", 75.00, 150.00),
    ("Hex bolts M8, box of 100", 8.50, 19.00),
    ("Hydraulic hose 3/8in (per ft)", 2.20, 6.75),
    ("Landscape fabric roll", 22.00, 48.00),
    ("Monthly hosting plan", 9.99, 49.99),
    ("Wireless keyboard", 24.00, 79.00),
    ("Espresso beans 1kg", 14.00, 32.00),
    ("Safety gloves, pair", 3.50, 11.00),
    ("Network cable Cat6 25ft", 7.99, 18.99),
    ("Ergonomic office chair", 149.00, 420.00),
]

CURRENCIES = ["USD", "USD", "USD", "USD", "EUR", "GBP", "JPY"]
TAX_RATES = [0.0, 0.05, 0.0625, 0.08, 0.0875, 0.10, 0.20]


@dataclass
class Fixture:
    doc_id: str
    kind: str      # clean_pdf | scan | photo | multipage | edge
    variant: str   # renderer/degradation detail or edge-case name
    truth: dict    # ground-truth Extraction dict


def _money(rng: random.Random, lo: float, hi: float, jpy: bool) -> float:
    v = rng.uniform(lo, hi)
    return float(round(v * 100)) if jpy else round(v, 2)


def make_invoice(rng: random.Random, *, currency: str | None = None, n_items: int | None = None,
                 edge: str | None = None) -> dict:
    vendor, address = rng.choice(VENDORS)
    currency = currency or rng.choice(CURRENCIES)
    jpy = currency == "JPY"
    n = n_items if n_items is not None else rng.randint(1, 6)

    items = []
    for _ in range(n):
        desc, lo, hi = rng.choice(PRODUCTS)
        qty = rng.choice([1, 1, 1, 2, 2, 3, 4, 5, 10])
        unit = _money(rng, lo, hi, jpy)
        items.append({
            "description": desc, "quantity": float(qty), "unit_price": unit,
            "amount": round(qty * unit, 2),
        })

    if edge == "negative_total":
        for it in items:
            it["unit_price"] = -abs(it["unit_price"])
            it["amount"] = round(it["quantity"] * it["unit_price"], 2)

    subtotal = round(sum(it["amount"] for it in items), 2)
    rate = 0.0 if jpy else rng.choice(TAX_RATES)
    tax = round(subtotal * rate, 2)
    total = round(subtotal + tax, 2)

    date = f"{rng.randint(2024, 2026)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
    inv_no = rng.choice([
        f"INV-{rng.randint(1000, 99999)}",
        f"{rng.randint(2024, 2026)}-{rng.randint(100, 999)}",
        f"R{rng.randint(100000, 999999)}",
    ])

    truth = {
        "vendor": vendor, "date": date, "invoice_no": inv_no,
        "line_items": items, "subtotal": subtotal, "tax": tax, "total": total,
        "currency": currency,
    }

    if edge == "missing_invoice_no":
        truth["invoice_no"] = None
    if edge == "missing_tax":
        truth["tax"] = None
        truth["total"] = subtotal
    if edge == "no_line_prices":
        # Receipt style: only line totals, no qty/unit breakdown printed.
        for it in truth["line_items"]:
            it["quantity"] = None
            it["unit_price"] = None

    truth["_meta"] = {"address": address, "edge": edge}
    return truth
