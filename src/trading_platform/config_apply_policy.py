from __future__ import annotations

from collections.abc import Mapping, Sequence


HOT_RELOADABLE_SECTION_PATHS = (
    "arbitrage_runtime.risk_config",
    "arbitrage_runtime.runtime_state.open_order_cap",
    "arbitrage_runtime.runtime_state.remaining_bot_notional",
)


def summarize_config_assignment_policy(
    previous_config: Mapping[str, object] | None,
    next_config: Mapping[str, object],
) -> dict[str, object]:
    if previous_config is None:
        changed_sections = ["initial_assignment"]
    else:
        changed_sections = sorted(_collapse_section_paths(_diff_paths(previous_config, next_config)))
        if not changed_sections:
            changed_sections = ["no_effective_change"]
    if changed_sections == ["no_effective_change"]:
        return {
            "apply_policy": "noop",
            "changed_sections": changed_sections,
            "hot_reloadable_sections": [],
            "restart_required_sections": [],
        }
    hot_reloadable_sections = [
        section for section in changed_sections if section in HOT_RELOADABLE_SECTION_PATHS
    ]
    restart_required_sections = [
        section for section in changed_sections if section not in hot_reloadable_sections
    ]
    if restart_required_sections:
        apply_policy = "restart_required"
    else:
        apply_policy = "hot_reload"
    return {
        "apply_policy": apply_policy,
        "changed_sections": changed_sections,
        "hot_reloadable_sections": hot_reloadable_sections,
        "restart_required_sections": restart_required_sections,
    }


def _diff_paths(
    previous: Mapping[str, object],
    current: Mapping[str, object],
    *,
    prefix: str = "",
) -> set[str]:
    keys = set(previous) | set(current)
    changed: set[str] = set()
    for key in keys:
        key_text = str(key)
        path = f"{prefix}.{key_text}" if prefix else key_text
        previous_value = previous.get(key_text)
        current_value = current.get(key_text)
        if isinstance(previous_value, Mapping) and isinstance(current_value, Mapping):
            changed.update(_diff_paths(previous_value, current_value, prefix=path))
            continue
        if _sequence_changed(previous_value, current_value):
            changed.add(path)
            continue
        if previous_value != current_value:
            changed.add(path)
    return changed


def _sequence_changed(previous_value: object, current_value: object) -> bool:
    if isinstance(previous_value, (str, bytes)) or isinstance(current_value, (str, bytes)):
        return False
    if isinstance(previous_value, Sequence) and isinstance(current_value, Sequence):
        return list(previous_value) != list(current_value)
    return False


def _collapse_section_paths(changed_paths: set[str]) -> set[str]:
    collapsed: set[str] = set()
    for path in changed_paths:
        hot_section = next(
            (
                section
                for section in HOT_RELOADABLE_SECTION_PATHS
                if path == section or path.startswith(f"{section}.")
            ),
            None,
        )
        collapsed.add(hot_section or path)
    return collapsed
