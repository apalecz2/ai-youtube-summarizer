"""Thin provider interface over the LLM.

v2 uses Gemini, but every call site goes through `generate()` here so items 3/4
(agentic deep-dives) can add Claude or a router later without touching the
summarizer or quiz code. Keep this surface small and provider-neutral.

Rate limiting: each model has its own input-tokens-per-minute quota. We track what
we've sent each model over the last 60s and (a) prefer a model that still has room,
(b) wait if none does, and (c) on a real 429 put that model on cooldown and fall
through to the next one. Other errors (e.g. a 503 "high demand") also fall through.
"""
import re
import threading
import time
from collections import deque
from typing import Any, Optional

from google import genai

from app import config, events
from app.config import GEMINI_API_KEY

# Fallback chain — first model that works wins. Order matters (best first).
MODELS = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
]

_WINDOW_SECONDS = 60
_DEFAULT_COOLDOWN_SECONDS = 60
_MAX_COOLDOWN_SECONDS = 120
_MAX_ROUNDS = 3              # passes over the whole chain before giving up
_CHARS_PER_TOKEN = 3.5       # conservative text estimate (English is ~4)


class LLMRateLimited(RuntimeError):
    """Every model in the chain was rate limited, even after waiting. The caller
    should retry the job later rather than record a failure."""


_client: genai.Client | None = None
_lock = threading.Lock()
_sent: dict[str, deque] = {m: deque() for m in MODELS}   # model -> deque of [ts, tokens]
_cooldown_until: dict[str, float] = {}


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY not set")
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def estimate_text_tokens(text: str) -> int:
    return int(len(text) / _CHARS_PER_TOKEN) + 1


def _budget() -> int:
    return config.GEMINI_INPUT_TOKENS_PER_MINUTE * config.GEMINI_TPM_SAFETY_PERCENT // 100


def _prune(model: str, now: float) -> None:
    q = _sent[model]
    while q and now - q[0][0] >= _WINDOW_SECONDS:
        q.popleft()


def _seconds_until_room(model: str, tokens: int, now: float) -> float:
    """0 if `tokens` fits in the model's window right now; else how long until enough
    older sends age out. A request bigger than the whole budget just needs an empty
    window (it can't be made to fit, and callers keep requests well under budget)."""
    _prune(model, now)
    q = _sent[model]
    used = sum(t for _, t in q)
    need = min(tokens, _budget())
    if used + need <= _budget():
        return 0.0
    over = used + need - _budget()
    freed = 0
    for ts, t in q:
        freed += t
        if freed >= over:
            return max(0.0, ts + _WINDOW_SECONDS - now)
    return float(_WINDOW_SECONDS)


def _is_rate_limit(e: Exception) -> bool:
    code = getattr(e, "code", None)
    s = str(e)
    return code == 429 or "RESOURCE_EXHAUSTED" in s or s.lstrip().startswith("429")


def _retry_delay(e: Exception) -> float:
    m = re.search(r"retry(?:Delay)?\D{0,12}(\d+(?:\.\d+)?)\s*s", str(e), re.IGNORECASE)
    d = float(m.group(1)) if m else _DEFAULT_COOLDOWN_SECONDS
    return min(max(d, 5.0), _MAX_COOLDOWN_SECONDS)


def generate(contents: Any, *, est_tokens: Optional[int] = None,
             config_: Any = None) -> tuple[str, str]:
    """Return (text, model_used). `contents` is a prompt string or genai Content;
    `est_tokens` is the expected input size (inferred for plain strings, required
    for anything else, e.g. video). Raises LLMRateLimited if every model is rate
    limited, RuntimeError if they all failed some other way."""
    if est_tokens is None:
        if not isinstance(contents, str):
            raise ValueError("est_tokens is required for non-string contents")
        est_tokens = estimate_text_tokens(contents)

    client = _get_client()
    last_error: Optional[Exception] = None
    saw_rate_limit = False

    for round_no in range(_MAX_ROUNDS):
        soonest_wait = float(_WINDOW_SECONDS)
        rate_limited_this_round = False
        for model in MODELS:
            now = time.time()
            with _lock:
                if _cooldown_until.get(model, 0) > now:
                    soonest_wait = min(soonest_wait, _cooldown_until[model] - now)
                    rate_limited_this_round = True
                    continue
                wait = _seconds_until_room(model, est_tokens, now)
                if wait > 0:
                    soonest_wait = min(soonest_wait, wait)
                    rate_limited_this_round = True
                    continue
                entry = [now, min(est_tokens, _budget())]
                _sent[model].append(entry)

            try:
                kwargs: dict[str, Any] = {"model": model, "contents": contents}
                if config_ is not None:
                    kwargs["config"] = config_
                resp = client.models.generate_content(**kwargs)
            except Exception as e:  # noqa: BLE001 - try the next model
                last_error = e
                if _is_rate_limit(e):
                    saw_rate_limit = rate_limited_this_round = True
                    delay = _retry_delay(e)
                    with _lock:
                        _cooldown_until[model] = time.time() + delay
                    soonest_wait = min(soonest_wait, delay)
                    events.log("warn", "llm", f"{model} rate limited; cooling it down {int(delay)}s")
                else:
                    with _lock:  # the request didn't use quota
                        try:
                            _sent[model].remove(entry)
                        except ValueError:
                            pass
                    events.log("warn", "llm", f"{model} failed: {type(e).__name__}: {str(e)[:200]}")
                continue

            # Replace our estimate with what the API actually counted.
            actual = getattr(getattr(resp, "usage_metadata", None), "prompt_token_count", None)
            if actual:
                with _lock:
                    entry[1] = actual
            text = resp.text.strip() if resp.text else ""
            if text:
                return text, model
            last_error = RuntimeError(f"{model} returned an empty response")

        if not rate_limited_this_round:
            break
        if round_no < _MAX_ROUNDS - 1:
            wait = min(soonest_wait, _MAX_COOLDOWN_SECONDS) + 1
            events.log("info", "llm", f"all models busy or rate limited; waiting {int(wait)}s")
            time.sleep(wait)

    if saw_rate_limit:
        raise LLMRateLimited(f"all Gemini models are rate limited: {last_error}")
    raise RuntimeError(f"All configured LLM models failed to generate content: {last_error}")


def count_tokens(contents: Any) -> int:
    """Input-token count for `contents` (free; used to size videos). Tries the chain."""
    client = _get_client()
    last: Optional[Exception] = None
    for model in MODELS:
        try:
            return client.models.count_tokens(model=model, contents=contents).total_tokens or 0
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"count_tokens failed on every model: {last}")
