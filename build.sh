#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

echo "=== Installing build deps ==="
uv pip install -e ".[build]"

echo "=== Building with PyInstaller ==="
.venv/bin/pyinstaller plan_finder_gui.spec --noconfirm

echo ""
if [ "$(uname)" = "Darwin" ]; then
    echo "=== Done: dist/PlanFinder.app ==="
    echo "Run:  open dist/PlanFinder.app"
else
    echo "=== Done: dist/PlanFinder/PlanFinder.exe ==="
fi
