#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi

mkdir -p "$ROOT_DIR/logs" "$ROOT_DIR/.tmp"

echo "virtualenv: $VENV_DIR"
echo "logs dir : $ROOT_DIR/logs"
echo "tmp dir  : $ROOT_DIR/.tmp"
echo "third-party dependencies are not installed automatically"
