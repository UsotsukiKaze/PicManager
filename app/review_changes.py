"""Helpers for comparing reviewable edits with their current values."""

from __future__ import annotations

from typing import Any, Mapping


ID_LIST_FIELDS = {"character_ids", "group_ids", "feature_tag_ids"}
TEXT_LIST_FIELDS = {"aliases", "nicknames"}
OPTIONAL_TEXT_FIELDS = {"description", "pid"}


def _normalized_value(field: str, value: Any) -> Any:
    """Normalize values according to how the corresponding service stores them."""
    if field in ID_LIST_FIELDS:
        if not value:
            return []
        normalized = []
        for item in value:
            try:
                normalized.append(int(item))
            except (TypeError, ValueError):
                normalized.append(item)
        return sorted(set(normalized), key=str)

    if field in TEXT_LIST_FIELDS:
        if not value:
            return []
        normalized = {
            item.strip()
            for item in value
            if isinstance(item, str) and item.strip()
        }
        return sorted(normalized)

    if field in OPTIONAL_TEXT_FIELDS and value in (None, ""):
        return ""

    return value


def build_changes(
    proposed: Mapping[str, Any],
    original: Mapping[str, Any],
    labels: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Return only fields whose proposed value differs from the original value."""
    labels = labels or {}
    changes = []
    for field, after in proposed.items():
        if field not in original:
            continue
        before = original[field]
        if _normalized_value(field, before) == _normalized_value(field, after):
            continue
        changes.append(
            {
                "field": field,
                "label": labels.get(field, field),
                "before": before,
                "after": after,
            }
        )
    return changes


def changed_update_data(
    proposed: Mapping[str, Any],
    original: Mapping[str, Any],
) -> dict[str, Any]:
    """Filter an update payload down to fields that would actually change."""
    changed_fields = {
        change["field"]
        for change in build_changes(proposed, original)
    }
    return {
        field: value
        for field, value in proposed.items()
        if field in changed_fields
    }
