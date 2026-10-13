"""Thin provider interface over the LLM.

v2 uses Gemini, but every call site goes through `generate()` here so items 3/4
(agentic deep-dives) can add Claude or a router later without touching the
summarizer or quiz code. Keep this surface small and provider-neutral.

Rate limiting, per model:
  * requests per DAY (RPD): counted in the DB per Pacific-time day. A model at its
    limit is skipped BEFORE a request is made, so the chain falls back to the next
    model without wasting a call on a certain 429. Counts survive restarts; they reset
    at midnight Pacific like Google's.
  * input tokens per MINUTE (TPM): tracked over a sliding 60s window; we prefer a model
    with room, and wait if none has any.
  * a real 429 puts that model on a short cooldown (or, if Google says it was the daily
    quota, marks it spent for the day) and falls through to the next one. Other errors
    (e.g. a 503 "high demand") also fall through.
"""
import re
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from google import genai

from app import config, events
from app.config import GEMINI_API_KEY
from app.db import repos

# Fallback chain — first model that works wins. Order matters (best first); the
# last one is the safety net. Daily request limits come from config.
MODELS = [m for m, _ in config.GEMINI_MODEL_CHAIN]
DAILY_LIMITS = dict(config.GEMINI_MODEL_CHAIN)

_PACIFIC = ZoneInfo("America/Los_Angeles")

_WINDOW_SECONDS = 60
_DEFAULT_COOLDOWN_SECONDS = 60
_MAX_COOLDOWN_SECONDS = 120
_MAX_ROUNDS = 3              # passes over the whole chain before giving up
_CHARS_PER_TOKEN = 3.5       # conservative text estimate (English is ~4)


class LLMRateLimited(RuntimeError):
    """Every model in the chain was rate limited / out of daily requests. The caller
    should retry the job later rather than record a failure. `retry_after` (seconds)
    is when that's worth trying; None means "soon"."""

    def __init__(self, message: str, retry_after: Optional[int] = None):
        super().__init__(message)
        self.retry_after = retry_after


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


# ── daily (RPD) accounting ────────────────────────────────────
def pacific_day() -> str:
    return datetime.now(_PACIFIC).date().isoformat()


def seconds_until_reset() -> int:
    now = datetime.now(_PACIFIC)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((midnight - now).total_seconds()))


_logged_spent: set[tuple[str, str]] = set()


def _log_spent_once(model: str, day: str) -> None:
    if (day, model) not in _logged_spent:
        _logged_spent.add((day, model))
        nxt = next((m for m in MODELS[MODELS.index(model) + 1:]), None)
        events.log("warn", "llm", f"{model} has used its {DAILY_LIMITS[model]} requests for {day}"
                   + (f" — falling back to {nxt}" if nxt else " — no models left until the reset"))


def remaining_requests() -> int:
    """Requests left today across the whole chain."""
    used = repos.llm_usage(pacific_day())
    return sum(max(0, DAILY_LIMITS[m] - used.get(m, {}).get("requests", 0)) for m in MODELS)


def ensure_capacity(requests_needed: int) -> None:
    """Fail fast, before any work is spent, if today's remaining requests can't
    cover a multi-request task (a sliced video / chunked transcript)."""
    left = remaining_requests()
    if left < requests_needed:
        raise LLMRateLimited(
            f"only {left} Gemini request(s) left today across all models, need {requests_needed}",
            retry_after=seconds_until_reset() + 60)


def _is_daily_quota(e: Exception) -> bool:
    s = re.sub(r"[\s_\-]", "", str(e)).lower()
    return "perday" in s or "daily" in s


def usage_snapshot() -> list[dict]:
    """Per-model usage today, for the System page, with a naive pace projection."""
    day = pacific_day()
    used = repos.llm_usage(day)
    now = datetime.now(_PACIFIC)
    elapsed = max(1.0, (now - now.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds())
    reset_in = seconds_until_reset()
    out = []
    for m in MODELS:
        u = used.get(m, {}).get("requests", 0)
        limit = DAILY_LIMITS[m]
        remaining = max(0, limit - u)
        # At today's average pace, when does it run out? (None if it won't before the reset.)
        projected = int(remaining / (u / elapsed)) if u > 0 and remaining > 0 else None
        if projected is not None and projected >= reset_in:
            projected = None
        with _lock:
            _prune(m, time.time())
            tpm = sum(t for _, t in _sent[m])
        out.append({"model": m, "limit": limit, "used": u, "remaining": remaining,
                    "tokens_today": used.get(m, {}).get("tokens", 0), "exhausted": remaining == 0,
                    "projected_exhaustion_in_seconds": projected, "resets_in_seconds": reset_in,
                    "tokens_last_minute": tpm, "tpm_budget": _budget()})
    return out


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
            day = pacific_day()
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
                # Daily request budget: checked and counted atomically BEFORE sending,
                # so a model that's out of requests is skipped without a doomed call.
                if not repos.reserve_llm_request(day, model, DAILY_LIMITS[model]):
                    _log_spent_once(model, day)
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
                with _lock:  # a failed request used no token quota
                    try:
                        _sent[model].remove(entry)
                    except ValueError:
                        pass
                if _is_rate_limit(e) and _is_daily_quota(e):
                    # Google says the DAILY quota is gone (our count was low, e.g. the
                    # same project is used elsewhere): spent for the rest of the day.
                    saw_rate_limit = True
                    repos.mark_llm_exhausted(day, model, DAILY_LIMITS[model])
                    events.log("warn", "llm", f"{model}: Google reports its daily quota is exhausted — "
                               "skipping it until the reset")
                elif _is_rate_limit(e):
                    saw_rate_limit = rate_limited_this_round = True
                    repos.refund_llm_request(day, model)   # rejected, so not counted against the day
                    delay = _retry_delay(e)
                    with _lock:
                        _cooldown_until[model] = time.time() + delay
                    soonest_wait = min(soonest_wait, delay)
                    events.log("warn", "llm", f"{model} rate limited; cooling it down {int(delay)}s")
                else:
                    repos.refund_llm_request(day, model)   # 5xx / network: assume not counted
                    events.log("warn", "llm", f"{model} failed: {type(e).__name__}: {str(e)[:200]}")
                continue

            # Replace our estimate with what the API actually counted.
            actual = getattr(getattr(resp, "usage_metadata", None), "prompt_token_count", None)
            if actual:
                with _lock:
                    entry[1] = actual
            repos.add_llm_tokens(day, model, actual or est_tokens)
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

    if remaining_requests() == 0:
        raise LLMRateLimited("every Gemini model has used its daily request limit "
                             f"(resets in {seconds_until_reset() // 3600}h)", retry_after=seconds_until_reset() + 60)
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
