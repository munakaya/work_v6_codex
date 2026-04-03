from __future__ import annotations


def list_config_versions(
    config_versions: dict[str, list[dict[str, object]]],
    config_scope: str,
) -> list[dict[str, object]]:
    return list(config_versions.get(config_scope, []))


def get_alert_detail(
    alerts: list[dict[str, object]],
    alert_id: str,
) -> dict[str, object] | None:
    for alert in alerts:
        if alert.get("alert_id") == alert_id:
            return alert
    return None
