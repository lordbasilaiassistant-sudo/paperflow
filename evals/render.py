"""Render ground-truth invoice data to PDF, then optionally degrade to scan/photo
images. One layout engine feeds every modality so eval deltas measure the
degradation, not a different document."""

import io
import random
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageChops, ImageEnhance, ImageFilter
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas as rl_canvas

# CAD/AUD render with a bare "$", so the currency is genuinely ambiguous with USD
# on the page — the model has to be wrong sometimes, which is the point.
SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "CAD": "$", "AUD": "$"}

_MONTHS = ["", "January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]

DATE_STYLES = {
    "iso": lambda y, m, d: f"{y:04d}-{m:02d}-{d:02d}",
    "us": lambda y, m, d: f"{m:02d}/{d:02d}/{y:04d}",
    "long": lambda y, m, d: f"{_MONTHS[m]} {d}, {y}",
    "dots": lambda y, m, d: f"{d:02d}.{m:02d}.{y:04d}",
    # Out-of-distribution style (abbreviated month, apostrophe 2-digit year) that
    # the normalizer does NOT explicitly handle — so date accuracy is earned, not
    # guaranteed by the fixture generator matching the parser.
    "compact": lambda y, m, d: f"{_MONTHS[m][:3]} {d} '{y % 100:02d}",
}


def _fmt_date(iso: str, style: str) -> str:
    y, m, d = (int(x) for x in iso.split("-"))
    return DATE_STYLES[style](y, m, d)


def _fmt_money(v: float | None, cur: str) -> str:
    if v is None:
        return ""
    sym = SYMBOLS.get(cur, "")
    if cur == "JPY":
        return f"{sym}{v:,.0f}"
    return f"{sym}{v:,.2f}"


def render_pdf(truth: dict, out_path: Path, *, layout: str = "classic", date_style: str = "us") -> None:
    W, H = LETTER
    c = rl_canvas.Canvas(str(out_path), pagesize=LETTER)
    cur = truth["currency"]
    meta = truth.get("_meta") or {}
    items = truth["line_items"]
    is_credit = (truth.get("total") or 0) < 0
    title = "CREDIT NOTE" if is_credit else ("RECEIPT" if layout == "receipt" else "INVOICE")

    def header(page_no: int) -> float:
        if layout == "modern":
            c.setFont("Helvetica-Bold", 22)
            c.drawRightString(W - 54, H - 60, title)
            c.setFont("Helvetica-Bold", 12)
            c.drawString(54, H - 60, truth["vendor"])
            c.setFont("Helvetica", 9)
            c.drawString(54, H - 74, meta.get("address", ""))
            y = H - 108
        else:
            c.setFont("Helvetica-Bold", 15)
            c.drawString(54, H - 56, truth["vendor"])
            c.setFont("Helvetica", 9)
            c.drawString(54, H - 70, meta.get("address", ""))
            c.setFont("Helvetica-Bold", 20)
            c.drawRightString(W - 54, H - 60, title)
            y = H - 100
        c.setFont("Helvetica", 10)
        if truth.get("invoice_no"):
            c.drawString(54, y, f"Invoice #: {truth['invoice_no']}")
        c.drawString(54, y - 14, f"Date: {_fmt_date(truth['date'], date_style)}")
        if page_no > 1:
            c.drawRightString(W - 54, y, f"Page {page_no}")
        return y - 40

    def table_head(y: float) -> float:
        c.setFont("Helvetica-Bold", 9)
        c.drawString(54, y, "DESCRIPTION")
        c.drawRightString(W - 250, y, "QTY")
        c.drawRightString(W - 160, y, "UNIT")
        c.drawRightString(W - 54, y, "AMOUNT")
        c.line(54, y - 4, W - 54, y - 4)
        return y - 20

    page = 1
    y = table_head(header(page))
    c.setFont("Helvetica", 9)
    for it in items:
        if y < 120:
            c.showPage()
            page += 1
            y = table_head(header(page))
            c.setFont("Helvetica", 9)
        c.drawString(54, y, (it["description"] or "")[:60])
        if it.get("quantity") is not None:
            c.drawRightString(W - 250, y, f"{it['quantity']:g}")
        if it.get("unit_price") is not None:
            c.drawRightString(W - 160, y, _fmt_money(it["unit_price"], cur))
        c.drawRightString(W - 54, y, _fmt_money(it["amount"], cur))
        y -= 15

    if y < 150:
        c.showPage()
        page += 1
        y = header(page)
    y -= 10
    c.line(W - 260, y + 8, W - 54, y + 8)
    c.setFont("Helvetica", 10)
    if truth.get("subtotal") is not None:
        c.drawRightString(W - 160, y, "Subtotal:")
        c.drawRightString(W - 54, y, _fmt_money(truth["subtotal"], cur))
        y -= 16
    if truth.get("tax") is not None:
        c.drawRightString(W - 160, y, "Tax:")
        c.drawRightString(W - 54, y, _fmt_money(truth["tax"], cur))
        y -= 16
    discount = meta.get("discount") or 0
    shipping = meta.get("shipping") or 0
    if discount:
        c.drawRightString(W - 160, y, "Discount:")
        c.drawRightString(W - 54, y, "-" + _fmt_money(discount, cur))
        y -= 16
    if shipping:
        c.drawRightString(W - 160, y, "Shipping:")
        c.drawRightString(W - 54, y, _fmt_money(shipping, cur))
        y -= 16
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(W - 160, y, "TOTAL:")
    c.drawRightString(W - 54, y, _fmt_money(truth["total"], cur))
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(54, 60, "Thank you for your business.")
    c.save()


def pdf_to_image(pdf_path: Path, scale: float = 2.0) -> Image.Image:
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        return pdf[0].render(scale=scale).to_pil().convert("RGB")
    finally:
        pdf.close()


def _noise(img: Image.Image, rng: random.Random, sigma: int, alpha: float = 0.12) -> Image.Image:
    """Blend in a little grain — visible texture, not document destruction."""
    noise = Image.effect_noise(img.size, sigma)
    if img.mode != "L":
        noise = noise.convert(img.mode)
    return Image.blend(img, noise, alpha)


def degrade_scan(img: Image.Image, rng: random.Random) -> Image.Image:
    """Flatbed-scan look: grayscale, slight rotation, noise, uneven contrast."""
    g = img.convert("L")
    g = g.rotate(rng.uniform(-1.5, 1.5), expand=True, fillcolor=255, resample=Image.BICUBIC)
    g = ImageEnhance.Contrast(g).enhance(rng.uniform(0.82, 0.95))
    g = ImageEnhance.Brightness(g).enhance(rng.uniform(0.92, 1.05))
    g = g.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 0.6)))
    g = _noise(g, rng, rng.randint(24, 48), alpha=rng.uniform(0.06, 0.14))
    for _ in range(rng.randint(20, 60)):  # dust specks
        x, y = rng.randint(0, g.width - 3), rng.randint(0, g.height - 3)
        g.paste(rng.randint(0, 120), (x, y, x + rng.randint(1, 3), y + rng.randint(1, 3)))
    return g


def degrade_photo(img: Image.Image, rng: random.Random) -> Image.Image:
    """Phone-photo look: perspective skew, rotation, shadow gradient, JPEG mush."""
    w, h = img.size
    pad = int(w * 0.06)
    canvas = Image.new("RGB", (w + 2 * pad, h + 2 * pad), (168, 158, 148))
    canvas.paste(img, (pad, pad))
    img = canvas
    w, h = img.size
    j = int(w * 0.035)
    quad = (
        rng.randint(0, j), rng.randint(0, j),
        rng.randint(0, j), h - rng.randint(0, j),
        w - rng.randint(0, j), h - rng.randint(0, j),
        w - rng.randint(0, j), rng.randint(0, j),
    )
    img = img.transform((w, h), Image.QUAD, quad, resample=Image.BICUBIC, fillcolor=(140, 132, 124))
    img = img.rotate(rng.uniform(-3.5, 3.5), expand=True, fillcolor=(140, 132, 124), resample=Image.BICUBIC)
    shadow = Image.new("L", img.size, 255)
    for yy in range(img.height):
        shadow.paste(int(255 - (yy / img.height) * rng.uniform(35, 70)), (0, yy, img.width, yy + 1))
    img = ImageChops.multiply(img, Image.merge("RGB", (shadow, shadow, shadow)))
    img = ImageEnhance.Color(img).enhance(0.9)
    img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 0.7)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=rng.randint(60, 78))
    buf.seek(0)
    return Image.open(buf).convert("RGB")
