# Repository Guidelines

## Project Structure & Module Organization
This repository is currently documentation-first. Start from `docs/README.md`. For implementation work, read `docs/11_implementation_tasks.md` first; for product context, read `docs/00_system_overview.md` first. Then drill into focused design files such as `docs/01_architecture.md`, `docs/04_operations.md`, or the grouped indexes `docs/05_strategy_and_risk.md`, `docs/06_exchange_adapters.md`, `docs/07_ui_and_control_plane.md`, and `docs/08_execution_plan.md`. Keep new design notes, decision records, and architecture writeups under `docs/`. If implementation code is added later, place runtime code in a dedicated top-level directory such as `platform/` or `src/` rather than mixing code with documentation.

## Build, Test, and Development Commands
No build system, package manager, or automated test suite is committed yet. For now, contributors mainly review and edit repository documents.

- `git status -sb`: quick check of modified and untracked files
- `rg --files docs`: list documentation files
- `sed -n '1,120p' docs/README.md`: inspect the document map
- `sed -n '1,120p' docs/00_system_overview.md`: inspect the top-level PRD

When application code is introduced, add the corresponding setup, run, and test commands to this guide in the same change.

- `PYTHONPATH=src ./.venv/bin/python tools_for_ai/exchange_key_loader_cases.py`: 거래소 키 로더의 경로 우선순위와 필드 정규화를 검증
- `PYTHONPATH=src ./.venv/bin/python tools_for_ai/exchange_key_ready_cases.py`: ready endpoint에 거래소 키 상태가 반영되는지 검증
- `PYTHONPATH=src ./.venv/bin/python tools_for_ai/private_exchange_connector_cases.py`: private 거래소 connector skeleton의 준비 상태를 검증
- `PYTHONPATH=src ./.venv/bin/python tools_for_ai/private_exchange_runtime_cases.py`: runtime API에서 private 거래소 connector 상태를 조회하는지 검증
- `PYTHONPATH=src ./.venv/bin/python tools_for_ai/market_data_rate_limit_cases.py`: market data rate limiter와 retry/backoff 설정을 검증
- `PYTHONPATH=src ./.venv/bin/python tools_for_ai/market_data_runtime_rate_limit_cases.py`: market-data/runtime 응답에 rate limit 설정이 반영되는지 검증
- `PYTHONPATH=src ./.venv/bin/python tools_for_ai/control_plane_write_guard_cases.py`: write API bearer token 보호와 per-IP 기본 rate limit이 401/429로 동작하는지 검증

## Coding Style & Naming Conventions
Use concise Markdown with clear section headings and short paragraphs. Prefer bullet lists for requirements, constraints, and decisions. Name new docs by purpose, not by date alone, for example `docs/architecture_overview.md` or `docs/exchange_adapter_notes.md`. Keep file and directory names lowercase with underscores.

## Testing Guidelines
There is no formal test framework yet. Treat review as document validation: verify terminology, consistency across the split files in `docs/`, and internal cross-references before submitting changes. If you add executable code, include a matching automated test path and document how to run it here.

## Commit & Pull Request Guidelines
There is no established commit history yet, so use short imperative commit messages with a clear scope, such as `docs: add contributor guide`. Pull requests should explain what changed, why it changed, and which files are affected. Include screenshots only when the change adds visual assets or rendered UI output.

## Security & Configuration Tips
Do not commit secrets, `.env` files, local credentials, or generated scratch outputs. Keep temporary investigation notes outside tracked paths unless they are intentionally curated project documentation.
