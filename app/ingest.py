"""Turn an uploaded file into text the extractor can work with.

Digital PDFs use the embedded text layer. Scanned PDFs (pages with almost no
text layer) and images fall back to Tesseract OCR. The first page is always
rendered to PNG so the review UI can show the document next to its fields.
"""

import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pypdf
import pypdfium2 as pdfium
import pytesseract
from PIL import Image, ImageOps

from app import config

# Chars per page below which we assume the PDF is a scan and OCR it instead.
MIN_TEXT_CHARS_PER_PAGE = 100
RENDER_SCALE = 2.5  # ~180 dpi; enough for OCR without huge images

_tesseract_ready: bool | None = None


def _resolve_tesseract() -> bool:
    global _tesseract_ready
    if _tesseract_ready is not None:
        return _tesseract_ready
    candidates = [config.TESSERACT_CMD] if config.TESSERACT_CMD else []
    candidates += [
        shutil.which("tesseract") or "",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        "/usr/bin/tesseract",
    ]
    for c in candidates:
        if c and Path(c).exists():
            pytesseract.pytesseract.tesseract_cmd = c
            _tesseract_ready = True
            return True
    _tesseract_ready = False
    return False


@dataclass
class IngestResult:
    text: str
    page_count: int
    source: str  # "pdf-text" | "pdf-ocr" | "image-ocr"
    preview: Image.Image | None = None
    warnings: list[str] = field(default_factory=list)


def _otsu_threshold(img: Image.Image) -> int:
    """Otsu's method on the grayscale histogram: split at the point that
    minimizes intra-class variance. Handles uneven lighting far better than a
    fixed cutoff."""
    hist = img.histogram()
    total = sum(hist)
    sum_all = sum(i * h for i, h in enumerate(hist))
    sum_bg = 0.0
    weight_bg = 0
    best, threshold = 0.0, 128
    for i in range(256):
        weight_bg += hist[i]
        if weight_bg == 0:
            continue
        weight_fg = total - weight_bg
        if weight_fg == 0:
            break
        sum_bg += i * hist[i]
        mean_bg = sum_bg / weight_bg
        mean_fg = (sum_all - sum_bg) / weight_fg
        between = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
        if between > best:
            best, threshold = between, i
    return threshold


def _preprocess_for_ocr(img: Image.Image) -> Image.Image:
    img = ImageOps.autocontrast(img.convert("L"))
    if img.width < 1400:
        ratio = 1400 / img.width
        img = img.resize((1400, int(img.height * ratio)), Image.LANCZOS)
    t = _otsu_threshold(img)
    return img.point(lambda p: 255 if p > t else 0)


def _ocr(img: Image.Image) -> str:
    if not _resolve_tesseract():
        raise RuntimeError(
            "Tesseract not found. Install it (https://github.com/UB-Mannheim/tesseract/wiki on Windows, "
            "`apt install tesseract-ocr` on Debian/Ubuntu) or set TESSERACT_CMD in .env."
        )
    # psm 4: single column of text of variable sizes — fits invoice tables better
    # than full auto (psm 3), which tends to drop right-aligned amount columns.
    return pytesseract.image_to_string(_preprocess_for_ocr(img), config="--psm 4")


def _render_pdf_page(pdf: pdfium.PdfDocument, index: int) -> Image.Image:
    return pdf[index].render(scale=RENDER_SCALE).to_pil()


def ingest(path: Path) -> IngestResult:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _ingest_pdf(path)
    if suffix in (".png", ".jpg", ".jpeg", ".webp", ".tiff", ".bmp"):
        return _ingest_image(path)
    raise ValueError(f"Unsupported file type: {suffix}")


def _ingest_pdf(path: Path) -> IngestResult:
    reader = pypdf.PdfReader(str(path))
    page_texts = [(page.extract_text() or "").strip() for page in reader.pages]
    n = len(page_texts)
    warnings: list[str] = []

    pdf = pdfium.PdfDocument(str(path))
    try:
        preview = _render_pdf_page(pdf, 0)
        ocr_pages = [i for i, t in enumerate(page_texts) if len(t) < MIN_TEXT_CHARS_PER_PAGE]
        if ocr_pages:
            for i in ocr_pages:
                try:
                    page_texts[i] = _ocr(_render_pdf_page(pdf, i)).strip()
                except RuntimeError as e:
                    warnings.append(str(e))
                    break
        source = "pdf-ocr" if len(ocr_pages) == n and n > 0 else "pdf-text"
    finally:
        pdf.close()

    text = "\n\n--- page break ---\n\n".join(page_texts)
    return IngestResult(text=text, page_count=n, source=source, preview=preview, warnings=warnings)


def _ingest_image(path: Path) -> IngestResult:
    img = Image.open(path)
    img.load()
    preview = img.convert("RGB")
    text = _ocr(img)
    return IngestResult(text=text.strip(), page_count=1, source="image-ocr", preview=preview)
