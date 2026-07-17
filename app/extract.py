"""LLM extraction: document text in, structured fields + per-field self-confidence out.

Flash-tier models drift on formats, so the contract is deliberately loose on the
model side (it may echo dates/amounts as seen) and strict on ours: normalize.py
canonicalizes everything before validation. Invalid JSON gets one repair retry.
"""

import json
import re
from dataclasses import dataclass, field

from app import llm
from app.normalize import normalize_extraction

SYSTEM_PROMPT = """You extract structured data from invoices and receipts.
Reply with a single JSON object and nothing else — no prose, no markdown fences.

Schema:
{
  "vendor": string|null,          // the business that ISSUED the document
  "date": string|null,            // invoice/receipt date exactly as printed
  "invoice_no": string|null,      // invoice/receipt/order number
  "line_items": [{"description": string|null, "quantity": number|null, "unit_price": number|null, "amount": number|null}],
  "subtotal": number|null,
  "tax": number|null,
  "total": number|null,           // the grand total actually charged
  "currency": string|null,        // 3-letter code; infer from symbol ($ -> USD, € -> EUR, £ -> GBP, ¥ -> JPY)
  "confidence": {"vendor": 0-1, "date": 0-1, "invoice_no": 0-1, "line_items": 0-1, "subtotal": 0-1, "tax": 0-1, "total": 0-1, "currency": 0-1}
}

Rules:
- Use null for anything not present in the document. Never invent values.
- Amounts are plain numbers without currency symbols or thousands separators.
- Credit notes / refunds have negative totals; keep the sign.
- The text may contain OCR noise (swapped characters, broken columns). Confidence
  should reflect how legible the source was: clean text -> 0.9+, garbled -> lower.
- "--- page break ---" separates pages of the same document; totals usually sit on the last page."""


@dataclass
class ExtractResult:
    extraction: dict
    model_confidence: dict
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    attempts: int = 1
    parse_failed: bool = False
    raw_response: str = ""
    warnings: list[str] = field(default_factory=list)


def _find_json(text: str) -> dict | None:
    """Pull the first balanced JSON object out of a possibly-noisy response."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i, ch in enumerate(text[start:], start):
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
        elif ch == '"' and not esc:
            in_str = not in_str
        elif not in_str:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        return None
    return None


EMPTY = {
    "vendor": None, "date": None, "invoice_no": None, "line_items": [],
    "subtotal": None, "tax": None, "total": None, "currency": None,
}


def extract(doc_text: str) -> ExtractResult:
    if not doc_text.strip():
        return ExtractResult(
            extraction=dict(EMPTY), model_confidence={}, parse_failed=True,
            warnings=["Document produced no text (empty OCR result?)"],
        )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Document text:\n\n{doc_text[:24000]}"},
    ]
    total_pt = total_ct = total_cost = 0.0
    attempts = 0
    raw = ""
    for attempt in range(2):
        attempts = attempt + 1
        resp = llm.chat(messages)
        total_pt += resp.prompt_tokens
        total_ct += resp.completion_tokens
        total_cost += resp.cost_usd
        raw = resp.content
        parsed = _find_json(raw)
        if parsed is not None:
            model_conf = parsed.pop("confidence", None)
            if not isinstance(model_conf, dict):
                model_conf = {}
            extraction = normalize_extraction({**EMPTY, **parsed})
            return ExtractResult(
                extraction=extraction, model_confidence=model_conf,
                prompt_tokens=int(total_pt), completion_tokens=int(total_ct),
                cost_usd=total_cost, attempts=attempts,
            )
        messages = messages[:2] + [
            {"role": "assistant", "content": raw[:2000]},
            {"role": "user", "content": "That was not valid JSON. Reply again with ONLY the JSON object, no other text."},
        ]
    return ExtractResult(
        extraction=dict(EMPTY), model_confidence={},
        prompt_tokens=int(total_pt), completion_tokens=int(total_ct), cost_usd=total_cost,
        attempts=attempts, parse_failed=True, raw_response=raw[:1000],
        warnings=["Model never returned parseable JSON"],
    )
