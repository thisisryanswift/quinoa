#!/bin/bash
# Canonical local/CI quality gate for Quinoa.
# Run from the project root.

set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> uv lock --check"
uv lock --check

echo "==> uv run ruff format --check quinoa tests"
uv run ruff format --check quinoa tests

echo "==> uv run ruff check quinoa tests"
uv run ruff check quinoa tests

echo "==> uv run mypy quinoa tests"
uv run mypy quinoa tests

echo "==> uv run pytest tests/python"
uv run pytest tests/python

# Pin PyO3 to the exact uv-managed Python executable and ensure Cargo test
# executables can find its libpython.
PYO3_PYTHON_EXE="$(uv run python -c 'import sys; print(sys.executable)')"
export PYO3_PYTHON="$PYO3_PYTHON_EXE"
export LD_LIBRARY_PATH="$("$PYO3_PYTHON_EXE" -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR"))')${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"

echo "==> cargo fmt --all -- --check"
cargo fmt --all -- --check

echo "==> cargo check --locked --no-default-features --features real-audio"
cargo check --locked --no-default-features --features real-audio

echo "==> cargo check --locked --no-default-features --features mock"
cargo check --locked --no-default-features --features mock

echo "==> cargo test --locked --no-default-features --features real-audio"
cargo test --locked --no-default-features --features real-audio

echo "==> bash -n scripts/bundle.sh"
bash -n scripts/bundle.sh

echo "==> desktop-file-validate quinoa.desktop"
if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate quinoa.desktop
else
    echo "desktop-file-validate not installed; skipping desktop entry validation."
    echo "Install desktop-file-utils to run this check locally, or rely on CI."
fi

echo "All checks passed."
