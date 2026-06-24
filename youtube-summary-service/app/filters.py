"""Per-channel video filtering.

Evaluation semantics for a given channel's rules:
  1. If the channel has any `include` rules, the video must match at least one
     of them to pass (an allowlist). This covers "filter out everything from
     this channel except videos whose title contains <phrase>".
  2. If the video matches any `exclude` rule, it is dropped.
  3. A channel with no rules passes everything (original behavior).

Designed to be extensible: add new `field` extractors to FIELD_GETTERS and new
`match_type` handlers to MATCHERS without touching the evaluation logic.
"""
from typing import Any, Callable, Mapping, Optional

# Allowed values, exposed so the API layer can validate input.
VALID_FIELDS = ("title",)
VALID_MATCH_TYPES = ("contains",)
VALID_ACTIONS = ("include", "exclude")


def _match_contains(value: str, target: str) -> bool:
    # Case-insensitive substring match.
    return value.strip().lower() in (target or "").lower()


# field name -> how to pull that field out of a video's attributes
FIELD_GETTERS: dict[str, Callable[[Mapping[str, Any]], Optional[str]]] = {
    "title": lambda video: video.get("title"),
}

# match_type -> comparison function (rule value, video field value) -> bool
MATCHERS: dict[str, Callable[[str, Any], bool]] = {
    "contains": _match_contains,
}


def _rule_matches(rule: Mapping[str, Any], video: Mapping[str, Any]) -> bool:
    getter = FIELD_GETTERS.get(rule["field"])
    matcher = MATCHERS.get(rule["match_type"])
    if getter is None or matcher is None:
        # Unknown rule type: ignore rather than crash polling.
        return False
    return matcher(rule["value"], getter(video))


def passes_filters(rules: list[Mapping[str, Any]], video: Mapping[str, Any]) -> bool:
    """Return True if `video` should be summarized given the channel's `rules`.

    `video` is a mapping of available fields, e.g. {"title": "..."}.
    """
    if not rules:
        return True

    includes = [r for r in rules if r["action"] == "include"]
    excludes = [r for r in rules if r["action"] == "exclude"]

    # Any exclude match drops the video outright.
    if any(_rule_matches(r, video) for r in excludes):
        return False

    # If there are include rules, at least one must match.
    if includes and not any(_rule_matches(r, video) for r in includes):
        return False

    return True
