"""CSV export of approved documents."""

import csv
import io

DOC_COLUMNS = [
    "id", "filename", "vendor", "date", "invoice_no", "currency",
    "subtotal", "tax", "total", "line_item_count", "doc_confidence", "approved_at",
]
ITEM_COLUMNS = [
    "document_id", "vendor", "date", "invoice_no", "currency",
    "description", "quantity", "unit_price", "amount",
]


def export_csv(docs: list[dict], mode: str = "documents") -> str:
    buf = io.StringIO()
    if mode == "line_items":
        w = csv.DictWriter(buf, fieldnames=ITEM_COLUMNS, lineterminator="\n")
        w.writeheader()
        for doc in docs:
            ex = doc.get("extraction") or {}
            base = {
                "document_id": doc["id"],
                "vendor": ex.get("vendor"),
                "date": ex.get("date"),
                "invoice_no": ex.get("invoice_no"),
                "currency": ex.get("currency"),
            }
            for it in ex.get("line_items") or []:
                w.writerow({**base, **{k: it.get(k) for k in ("description", "quantity", "unit_price", "amount")}})
    else:
        w = csv.DictWriter(buf, fieldnames=DOC_COLUMNS, lineterminator="\n")
        w.writeheader()
        for doc in docs:
            ex = doc.get("extraction") or {}
            w.writerow({
                "id": doc["id"],
                "filename": doc["filename"],
                "vendor": ex.get("vendor"),
                "date": ex.get("date"),
                "invoice_no": ex.get("invoice_no"),
                "currency": ex.get("currency"),
                "subtotal": ex.get("subtotal"),
                "tax": ex.get("tax"),
                "total": ex.get("total"),
                "line_item_count": len(ex.get("line_items") or []),
                "doc_confidence": doc.get("doc_confidence"),
                "approved_at": doc.get("updated_at"),
            })
    return buf.getvalue()
