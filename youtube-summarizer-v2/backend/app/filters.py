"""Per-channel video filtering — carried over verbatim from v1 (same semantics).

  1. If the channel has any `include` rules, the video must match at least one.
  2. Any `exclude` match drops the video.
  3. No rules => everything passes.

Extensible: add `field` extractors to FIELD_GETTERS and `match_type` handlers to
MATCHERS without touching the evaluation logic.
"""
from typing import Any, Callable, Mapping, Optional

VALID_FIELDS = ("title",)
VALID_MATCH_TYPES = ("contains",)
VALID_ACTIONS = ("include", "exclude")


def _match_contains(value: str, target: str) -> bool:
    return value.strip().lower() in (target or "").lower()


FIELD_GETTERS: dict[str, Callable[[Mapping[str, Any]], Optional[str]]] = {
    "title": lambda video: video.get("title"),
}

MATCHERS: dict[str, Callable[[str, Any], bool]] = {
    "contains": _match_contains,
}


def _rule_matches(rule: Mapping[str, Any], video: Mapping[str, Any]) -> bool:
    getter = FIELD_GETTERS.get(rule["field"])
    matcher = MATCHERS.get(rule["match_type"])
    if getter is None or matcher is None:
        return False
    return matcher(rule["value"], getter(video))


def passes_filters(rules: list[Mapping[str, Any]], video: Mapping[str, Any]) -> bool:
    if not rules:
        return True
    includes = [r for r in rules if r["action"] == "include"]
    excludes = [r for r in rules if r["action"] == "exclude"]
    if any(_rule_matches(r, video) for r in excludes):
        return False
    if includes and not any(_rule_matches(r, video) for r in includes):
        return False
    return True
