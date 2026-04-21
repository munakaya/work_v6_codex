from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionModeMetadata:
    normalized_mode: str
    path_kind: str
    temporary_path: bool
    summary: str


def describe_execution_mode(mode: str) -> ExecutionModeMetadata:
    normalized = mode.strip().lower() or "simulate_success"
    if normalized not in {
        "simulate_success",
        "simulate_failure",
        "simulate_fill",
        "private_http",
        "private_connectors",
        "private_stub",
    }:
        normalized = "simulate_failure"
    if normalized == "private_http":
        return ExecutionModeMetadata(
            normalized_mode=normalized,
            path_kind="temporary_external_delegate",
            temporary_path=True,
            summary=(
                "private_http delegates order submission to an external executor "
                "and remains a temporary live path"
            ),
        )
    if normalized == "private_connectors":
        return ExecutionModeMetadata(
            normalized_mode=normalized,
            path_kind="integrated_private_connectors",
            temporary_path=False,
            summary=(
                "private_connectors submits limit orders through in-process private exchange connectors"
            ),
        )
    if normalized == "private_stub":
        return ExecutionModeMetadata(
            normalized_mode=normalized,
            path_kind="stubbed_private_connector",
            temporary_path=True,
            summary="private_stub is a non-live placeholder execution path",
        )
    return ExecutionModeMetadata(
        normalized_mode=normalized,
        path_kind="simulated",
        temporary_path=False,
        summary="simulate_* modes do not submit live orders",
    )
