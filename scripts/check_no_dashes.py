"""Fail if an en dash, em dash or similar appears in any tracked text file.

Ground rule 8: no en or em dashes in code comments, documentation, commit
messages, UI copy or any other output. Use commas, colons or parentheses.

This is a script rather than a grep one liner because the grep available on a
given machine may not support the Unicode escapes needed (the Git Bash build on
the development machine rejects \\x{2014} outright), and because box drawing
characters must be allowed: the architecture diagrams are built from them and
they are not dashes.

Usage:
    python scripts/check_no_dashes.py           # checks git tracked files
    python scripts/check_no_dashes.py <paths>   # checks the given paths
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Codepoint: name, for a message that says what was actually found.
FORBIDDEN = {
    "‐": "HYPHEN (U+2010)",
    "‑": "NON-BREAKING HYPHEN (U+2011)",
    "‒": "FIGURE DASH (U+2012)",
    "–": "EN DASH (U+2013)",
    "—": "EM DASH (U+2014)",
    "―": "HORIZONTAL BAR (U+2015)",
    "−": "MINUS SIGN (U+2212)",
}

TEXT_SUFFIXES = {
    ".md", ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".yml", ".yaml",
    ".toml", ".sh", ".html", ".css", ".txt", ".cfg", ".ini", ".ipynb",
}

SKIP_DIRS = {".git", "node_modules", "tools", "dist", ".venv", "__pycache__"}

# This file necessarily contains the characters it forbids, in FORBIDDEN above.
SELF = Path(__file__).name


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        # Not a git repo, or git unavailable. Walk the tree instead so the
        # check still works, rather than passing vacuously.
        return [
            path
            for path in REPO_ROOT.rglob("*")
            if path.is_file() and not SKIP_DIRS & set(path.relative_to(REPO_ROOT).parts)
        ]
    names = [n for n in result.stdout.split("\0") if n]
    return [REPO_ROOT / name for name in names]


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        candidates = [Path(a) for a in argv[1:]]
    else:
        candidates = tracked_files()

    findings: list[str] = []
    checked = 0

    for path in candidates:
        if not path.is_file():
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if path.name == SELF:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        checked += 1
        for line_number, line in enumerate(text.splitlines(), start=1):
            for char, name in FORBIDDEN.items():
                if char in line:
                    column = line.index(char) + 1
                    try:
                        shown = path.relative_to(REPO_ROOT)
                    except ValueError:
                        shown = path
                    findings.append(f"{shown}:{line_number}:{column}: {name}")

    if findings:
        print(f"Found {len(findings)} forbidden dash character(s):", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        print(
            "\nGround rule 8: use commas, colons or parentheses instead.",
            file=sys.stderr,
        )
        return 1

    print(f"no forbidden dash characters in {checked} text file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
