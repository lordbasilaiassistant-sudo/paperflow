# paperflow — build state

Updated: 2026-07-17

## Current phase: P1, P2, P3, P3b complete; P4 (README+CI) done → P5 clean-clone test next

## Final eval numbers (118 docs, glm-4.5-flash free tier, `python -m evals.run`)
- Field accuracy **94.8%**; 77/118 (65.3%) fully correct.
- Routing: **78.0% auto-accepted at 98.1% field accuracy**; 22% to review at 82.9%.
- Material false accepts (auto-accepted with wrong vendor/date/amount/currency): **11 (12.0%)** — mostly
  OCR errors on photos/scans + irreducible currency ambiguity (CAD printed as "$"). Dialable: 0.90 → 8.3%, 0.95 → 6.0%.
- Per category: clean_pdf 100%, multipage 100%, scan 94.9%, edge 97.9%, photo 82.3% (honest OCR degradation).
- Weak spots (both OCR on degraded images, all on scan/photo): subtotal 79.7%, photo category 82.3%.
- ~868 tokens/doc, $0 on free tier. README table generated from results via `python -m evals.report_md`
  (guaranteed to match `evals.run`).
- Verified NOT inflated: numbers came down when the eval was hardened; date rose 70→99% only after genuinely
  handling the apostrophe-year format (real improvement, not gaming).

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
- Unit tests: **41/41 passing** (`py -m pytest`) — normalize (incl. all fixed parse bugs), validation
  (warnings vs errors), confidence (grounding, required-field gating, hallucination rejection), JSON parsing, export.
- Lint clean (`ruff check .`).
- P2 review UI verified end-to-end in Chrome: upload 4 docs over HTTP → routed → corrected an OCR-mangled
  credit note in the review pane (Save & re-check cleared all validation errors) → approved → CSV export. No console errors.
- P3 full eval run green (see numbers above); report table generated from results and pasted into README.
- Live end-to-end against z.ai `glm-4.5-flash` (thinking disabled).
- Tesseract 5.4 installed locally (winget UB-Mannheim build).
- Concurrency: pypdfium/tesseract native calls crash under threads (exit 127) → serialized with a lock; LLM
  calls stay concurrent. Free-tier 429s handled with backoff+jitter+Retry-After (workers=2 for the full run).

## Unverified / not built yet
- **P5 clean-clone test** — fresh clone in temp dir, follow README quickstart verbatim, fix friction. NOT done.
- Repo created (github.com/lordbasilaiassistant-sudo/paperflow, empty) + CI secret LLM_API_KEY set + topics.
  NOT pushed yet — push after P5.
- CI (.github/workflows/ci.yml) written but not yet observed green on GitHub (runs on first push).

## Key design decisions
- No vision model: z.ai free tier only has text glm-4.5-flash (vision models returned "insufficient balance").
  Images/scans go tesseract OCR (Otsu binarize + psm 4) → same text pipeline.
- Confidence blends model self-report + **source-text grounding** (value must appear in the doc) + non-trivial
  arithmetic corroboration; auto-accept gates on vendor/date/total being present, grounded, above a floor.
- Fixtures regenerated deterministically (seeded), not committed. README numbers come from `evals.report_md`.
- `LLM_EXTRA_BODY` env passes provider extras (z.ai `thinking: disabled`).

## Next step
P5: fresh clone in a temp dir, follow README quickstart exactly with a clean venv, fix any friction, then
push to GitHub and confirm CI goes green.

## Blockers
None.
