import traceback
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from app import config, db, export, pipeline
from app.models import Extraction

app = FastAPI(title="paperflow")

ALLOWED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
STATIC_DIR = Path(__file__).parent / "static"


def _process_document(doc_id: str, path: Path) -> None:
    conn = db.connect()
    try:
        result = pipeline.process(path)
        preview_note = _save_preview(doc_id, path)
        db.update_document(
            conn, doc_id,
            status="auto_accepted" if result.route == "auto_accept" else "needs_review",
            source_type=result.source_type,
            page_count=result.page_count,
            raw_text=result.raw_text,
            extraction=result.extraction,
            model_confidence=result.model_confidence,
            field_confidence=result.field_confidence,
            validation_issues=result.issues,
            doc_confidence=result.doc_confidence,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            cost_usd=result.cost_usd,
            error="; ".join(result.warnings + ([preview_note] if preview_note else [])) or None,
        )
    except Exception as e:
        traceback.print_exc()
        db.update_document(conn, doc_id, status="failed", error=f"{type(e).__name__}: {e}")
    finally:
        conn.close()


def _save_preview(doc_id: str, path: Path) -> str | None:
    """Render/copy a first-page PNG for the review UI. Non-fatal on failure."""
    try:
        from app.ingest import RENDER_SCALE

        out = config.PAGE_DIR / f"{doc_id}.png"
        if path.suffix.lower() == ".pdf":
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(str(path))
            try:
                pdf[0].render(scale=RENDER_SCALE).to_pil().save(out)
            finally:
                pdf.close()
        else:
            from PIL import Image

            Image.open(path).convert("RGB").save(out)
        return None
    except Exception as e:
        return f"preview failed: {e}"


@app.post("/api/documents")
async def upload(file: UploadFile, background: BackgroundTasks):
    suffix = Path(file.filename or "upload").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(400, f"Unsupported file type '{suffix}'. Use pdf/png/jpg/webp.")
    conn = db.connect()
    try:
        doc_id = db.create_document(conn, file.filename or f"upload{suffix}")
    finally:
        conn.close()
    dest = config.UPLOAD_DIR / f"{doc_id}{suffix}"
    dest.write_bytes(await file.read())
    background.add_task(_process_document, doc_id, dest)
    return {"id": doc_id, "status": "processing"}


@app.get("/api/documents")
def list_documents(status: str | None = None):
    conn = db.connect()
    try:
        docs = db.list_documents(conn, status)
    finally:
        conn.close()
    for d in docs:
        d.pop("raw_text", None)
    return docs


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str):
    conn = db.connect()
    try:
        doc = db.get_document(conn, doc_id)
    finally:
        conn.close()
    if not doc:
        raise HTTPException(404, "No such document")
    return doc


@app.get("/api/documents/{doc_id}/image")
def get_image(doc_id: str):
    path = config.PAGE_DIR / f"{doc_id}.png"
    if not path.exists():
        raise HTTPException(404, "No preview for this document")
    return FileResponse(path, media_type="image/png")


@app.patch("/api/documents/{doc_id}")
def update_fields(doc_id: str, extraction: Extraction):
    from app import confidence, validation

    conn = db.connect()
    try:
        doc = db.get_document(conn, doc_id)
        if not doc:
            raise HTTPException(404, "No such document")
        ex = extraction.model_dump()
        issues = validation.validate(ex)
        scored = confidence.score(ex, doc.get("model_confidence") or {}, issues)
        db.update_document(
            conn, doc_id, extraction=ex, validation_issues=issues,
            field_confidence=scored["fields"], doc_confidence=scored["doc"],
        )
        return db.get_document(conn, doc_id)
    finally:
        conn.close()


@app.post("/api/documents/{doc_id}/approve")
def approve(doc_id: str):
    conn = db.connect()
    try:
        doc = db.get_document(conn, doc_id)
        if not doc:
            raise HTTPException(404, "No such document")
        if doc["status"] not in ("needs_review", "auto_accepted"):
            raise HTTPException(409, f"Cannot approve a document in status '{doc['status']}'")
        db.update_document(conn, doc_id, status="approved")
        return db.get_document(conn, doc_id)
    finally:
        conn.close()


@app.get("/api/export.csv")
def export_csv(mode: str = "documents", status: str = "approved"):
    if mode not in ("documents", "line_items"):
        raise HTTPException(400, "mode must be 'documents' or 'line_items'")
    conn = db.connect()
    try:
        docs = db.list_documents(conn, status)
    finally:
        conn.close()
    csv_text = export.export_csv(docs, mode)
    return Response(
        csv_text, media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=paperflow_{mode}.csv"},
    )


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
