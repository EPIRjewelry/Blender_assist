#!/usr/bin/env python3
"""Fail CI if unresolved git merge conflict markers remain in source files."""

from __future__ import annotations

import sys
from pathlib import Path

SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", ".cloudflared"}
EXTENSIONS = {".py", ".ps1", ".md", ".toml", ".yml", ".json", ".example"}
MARKER = "<<<<<<< "


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    bad: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in EXTENSIONS:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if any(line.startswith(MARKER) for line in text.splitlines()):
            bad.append(path.relative_to(root))
    if bad:
        print("Unresolved merge conflict markers found:", file=sys.stderr)
        for item in bad:
            print(f"  {item}", file=sys.stderr)
        return 1
    print("OK: no conflict markers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
