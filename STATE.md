# paperflow — build state

Updated: 2026-07-17

## Current phase: P1, P2 complete; P3 harness built + hardened (P3b) → full eval running

## P3b hardening (from adversarial multi-agent review — 15 verified findings)
The first eval was partly self-fulfilling. Fixed, verified by 41 unit tests + live sanity check:
- **parse_amount**: `1.500`→1500 (was 1.5), `1.000.000`→1000000 (was None), `1,2`→1.2 (was 12). Real 1000x bugs.
- **parse_date**: currency-aware day-first for ambiguous slash dates (EUR/GBP → DD/MM) instead of silent US default.
- **validation**: arithmetic mismatches are now warnings (route to review) not errors — real invoices with
  discounts/shipping/tax-inclusive totals legitimately don't reconcile. total-check requires tax present (no
  treating missing tax as 0).
- **confidence**: added SOURCE-TEXT GROUNDING — a value the model is confident about but that isn't in the
  document is capped low; auto-accept gates on vendor+date+total being present, grounded, and above a floor.
  This closes the "internally-consistent hallucination auto-accepts" hole. Arithmetic boost now requires
  genuinely independent numbers (real line items), not a lone total equal to itself.
- **eval scoring**: line items now score description/quantity/unit_price/amount (was amount-only), with a
  per-attribute breakdown. Corpus adds non-reconciling docs (discount+shipping), currency ambiguity (CAD as
  "$"), non-zero JPY tax, and an out-of-distribution date format ("Sep 16 '26") the normalizer does NOT handle
  — so date/currency accuracy is earned, not guaranteed by round-tripping through the parser.
- Corpus now 118 fixtures. Sanity check confirmed: compact dates fail honestly, CAD→USD miss is real,
  adjustments route to review correctly.

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
