#!/usr/bin/env python3
"""Validate command files, one or many.

The unit tests pin the engine's rules against small hand-written fixtures.
This runs the same rules over real work, which is where authoring habits the
fixtures never imagined show up.

It shares its logic with `kitty-demo.py --check` rather than reimplementing it,
so a file that passes here passes there. The difference is only scope: this
walks a directory, and `--check` takes one file.

    tools/validate_command_files.py ~/path/to/exercises
    tools/validate_command_files.py one-exercise.sh

Exits nonzero when any file fails to parse.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kittydemo.engine import CommandFileError, parse  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2

    root = Path(argv[1]).expanduser()
    files = sorted(root.rglob("*.sh")) if root.is_dir() else [root]
    if not files:
        print(f"No command files under {root}")
        return 1

    errors: list[str] = []
    presses = 0
    parsed = 0

    for path in files:
        source = path.read_text()
        try:
            steps = parse(source)
        except CommandFileError as error:
            errors.append(f"{path.name}: {error}")
            continue

        parsed += 1
        presses += len(steps)

    print(f"parsed {parsed}/{len(files)} command files, {presses} presses")

    print(f"\nPARSE ERRORS: {len(errors)}")
    for entry in errors:
        print(f"  {entry}")

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
