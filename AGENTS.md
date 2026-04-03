# Repository Guidelines

## Project Structure & Module Organization
This repository is currently documentation-first. The main tracked artifact is `docs/codex_result.md`, which contains the product requirements document for the trading platform. Keep new design notes, decision records, and architecture writeups under `docs/`. If implementation code is added later, place runtime code in a dedicated top-level directory such as `platform/` or `src/` rather than mixing code with documentation.

## Build, Test, and Development Commands
No build system, package manager, or automated test suite is committed yet. For now, contributors mainly review and edit repository documents.

- `git status -sb`: quick check of modified and untracked files
- `rg --files docs`: list documentation files
- `sed -n '1,120p' docs/codex_result.md`: inspect the current PRD

When application code is introduced, add the corresponding setup, run, and test commands to this guide in the same change.

## Coding Style & Naming Conventions
Use concise Markdown with clear section headings and short paragraphs. Prefer bullet lists for requirements, constraints, and decisions. Name new docs by purpose, not by date alone, for example `docs/architecture_overview.md` or `docs/exchange_adapter_notes.md`. Keep file and directory names lowercase with underscores.

## Testing Guidelines
There is no formal test framework yet. Treat review as document validation: verify terminology, consistency with `docs/codex_result.md`, and internal cross-references before submitting changes. If you add executable code, include a matching automated test path and document how to run it here.

## Commit & Pull Request Guidelines
There is no established commit history yet, so use short imperative commit messages with a clear scope, such as `docs: add contributor guide`. Pull requests should explain what changed, why it changed, and which files are affected. Include screenshots only when the change adds visual assets or rendered UI output.

## Security & Configuration Tips
Do not commit secrets, `.env` files, local credentials, or generated scratch outputs. Keep temporary investigation notes outside tracked paths unless they are intentionally curated project documentation.
