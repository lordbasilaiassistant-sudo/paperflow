"""End-to-end pipeline for one document: ingest -> extract -> validate -> score.

Used by both the API (per upload) and the eval harness (per fixture), so eval
numbers measure exactly what production runs.
"""

from dataclasses import dataclass, field
from pathlib import Path

from app import confidence, extract, ingest, validation


@dataclass
class PipelineResult:
    extraction: dict
    model_confidence: dict
    field_confidence: dict
    issues: list[dict]
    doc_confidence: float
    route: str  # "auto_accept" | "needs_review"
    source_type: str
    page_count: int
    raw_text: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    warnings: list[str] = field(default_factory=list)


def process(path: Path) -> PipelineResult:
    ing = ingest.ingest(path)
    ext = extract.extract(ing.text)
    issues = validation.validate(ext.extraction)
    scored = confidence.score(
        ext.extraction, ext.model_confidence, issues, parse_failed=ext.parse_failed
    )
    return PipelineResult(
        extraction=ext.extraction,
        model_confidence=ext.model_confidence,
        field_confidence=scored["fields"],
        issues=issues,
        doc_confidence=scored["doc"],
        route=scored["route"],
        source_type=ing.source,
        page_count=ing.page_count,
        raw_text=ing.text,
        prompt_tokens=ext.prompt_tokens,
        completion_tokens=ext.completion_tokens,
        cost_usd=ext.cost_usd,
        warnings=ing.warnings + ext.warnings,
    )
