"""Thin client for any OpenAI-compatible chat endpoint.

Retries transient failures (429/5xx/timeouts) with exponential backoff so the
free-tier rate limits don't turn into user-facing errors.
"""

import time
from dataclasses import dataclass

import httpx

from app import config


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResponse:
    content: str
    prompt_tokens: int
    completion_tokens: int

    @property
    def cost_usd(self) -> float:
        return (
            self.prompt_tokens * config.LLM_PRICE_INPUT_PER_M
            + self.completion_tokens * config.LLM_PRICE_OUTPUT_PER_M
        ) / 1_000_000


RETRIABLE = {429, 500, 502, 503, 504}


def chat(messages: list[dict], *, temperature: float = 0.0, max_retries: int = 4, timeout: float = 120.0) -> LLMResponse:
    if not config.LLM_API_KEY:
        raise LLMError("LLM_API_KEY is not set. Copy .env.example to .env and add your key.")
    payload = {"model": config.LLM_MODEL, "messages": messages, "temperature": temperature}
    payload.update(config.LLM_EXTRA_BODY)
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        if attempt:
            time.sleep(min(2**attempt, 20))
        try:
            r = httpx.post(
                f"{config.LLM_BASE_URL}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
                timeout=timeout,
            )
        except httpx.HTTPError as e:
            last_err = e
            continue
        if r.status_code in RETRIABLE:
            last_err = LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
            continue
        if r.status_code != 200:
            raise LLMError(f"HTTP {r.status_code}: {r.text[:500]}")
        data = r.json()
        usage = data.get("usage") or {}
        try:
            content = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as e:
            raise LLMError(f"Malformed response: {str(data)[:300]}") from e
        return LLMResponse(
            content=content,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
        )
    raise LLMError(f"Gave up after {max_retries + 1} attempts: {last_err}")
