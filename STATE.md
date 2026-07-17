# paperflow — build state

Updated: 2026-07-17

## Current phase: P1 complete → starting P2

## Verified (executed, output checked)
- Unit tests: 32/32 passing (`py -m pytest`) — normalize, validation, confidence, JSON parsing, CSV export.
- Lint clean (`ruff check .`).
- Live end-to-end against z.ai `glm-4.5-flash` (thinking disabled):
  - Clean generated PDF → extraction exactly matched ground truth, `auto_accept`, doc_conf 1.0 (~650 tokens).
  - Degraded scan PNG → OCR (tesseract, Otsu binarize + psm 4) → exact match, `auto_accept`, 0.99.
  - Degraded phone-photo JPG → OCR misread subtotal (36.82→36.02); `total_mismatch` validator caught it → `needs_review` at 0.75. Routing works as designed.
- Tesseract 5.4 installed locally (winget UB-Mannheim build).

## Unverified / not built yet
- Review UI (stub index.html only) — P2.
- Full eval harness + 100 fixtures — P3 (generator + renderer exist and are live-tested on 3 docs, not at fixture scale).
- CI, README — P4/P5.
- FastAPI endpoints written but not yet exercised over HTTP (pipeline verified as library only).

## Key design decisions
- No vision model: z.ai free tier only has text glm-4.5-flash (vision models returned "insufficient balance" — verified 2026-07-17). Images/scans go tesseract OCR → same text pipeline.
- Confidence = model self-report blended with deterministic evidence; arithmetic agreement boosts to 0.97, validation errors cap at 0.30 and force review regardless of score.
- Fixtures are regenerated deterministically (seeded) rather than committed.
- `LLM_EXTRA_BODY` env passes provider extras (z.ai `thinking: disabled` — without it, ~280 thinking tokens per trivial call).

## Next step
P2: review UI (premium bar — own the art direction), routing views, export button; exercise HTTP endpoints for real.

## Blockers
None.
