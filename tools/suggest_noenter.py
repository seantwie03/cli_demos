#!/usr/bin/env python3
"""Propose `#@ noenter` for keystrokes that act the moment they arrive.

Every line in a command file gets an Enter unless it says otherwise, which is
right at a shell prompt and right for most lines inside an editor too, because
there the Enter is the newline. The exceptions are keystrokes that complete on
arrival: `q` leaving a pager, `dd` deleting a line, `ciw` starting a change.
Those need `#@ noenter`, or the Enter lands somewhere it was not wanted.

This is an authoring aid, not a rule. It reads the shape of a line and proposes
an annotation; the decision stays with the author, who reviews the suggestions
and applies them. Nothing validates that the result is complete or correct,
because no pattern can know whether a given line is inside an editor. Playing
the exercise back is what proves it.

    tools/suggest_noenter.py path/            # show suggestions
    tools/suggest_noenter.py path/ --apply    # insert them
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kittydemo.engine import DIRECTIVE, classify  # noqa: E402

#: Keystrokes that finish on arrival. Deliberately narrow: a suggestion that
#: has to be rejected costs more attention than one that was never made.
IMMEDIATE = re.compile(
    r"^(?:"
    r"q|Q|:q!?|ZZ|ZQ"  # leave a pager or editor
    r"|[ioOaAG]"  # enter insert mode, or jump
    r"|gg"
    r"|[cdy]{2}"  # dd, yy, cc
    r"|[cdy][iat][\w({\[<'\"]"  # ciw, dap, yi(
    r"|[cdy][wWbBeE$^0]"  # cw, db, y$
    r"|[cdy][fFtT]."  # ct; df, yt)
    r"|[wWbBeE]{2,}"  # repeated word motions such as www; bare w is a command
    r"|jj"  # the lab hosts map jj to Escape
    r"|\^\w"  # control keys such as ^X
    r")$"
)

#: Shapes `IMMEDIATE` would catch that are also real shell commands. Proposing
#: `#@ noenter` for one of these would break it, so they are never suggested.
#: Only `w` collides; `i`, `o`, `a`, `b` and `e` are not commands on RHEL.
AMBIGUOUS = frozenset({"w"})


def suggestions(source: str) -> list[tuple[int, str]]:
    """Lines that look like an immediate keystroke and are not yet annotated."""
    found: list[tuple[int, str]] = []
    annotated = False
    for number, raw in enumerate(source.splitlines(), start=1):
        text = raw.strip()
        if not text:
            continue
        if classify(raw) == "directive":
            annotated = raw.lstrip()[len(DIRECTIVE) :].split()[:1] == ["noenter"]
            continue
        if classify(raw) in {"header", "note", "continuation"}:
            continue
        if not annotated and text not in AMBIGUOUS and IMMEDIATE.match(text):
            found.append((number, text))
        annotated = False
    return found


def apply(path: Path, proposed: list[tuple[int, str]]) -> None:
    """Insert the directive above each accepted line, deepest line first."""
    lines = path.read_text().splitlines(keepends=True)
    for number, _ in sorted(proposed, reverse=True):
        indent = re.match(r"\s*", lines[number - 1]).group(0)
        lines.insert(number - 1, f"{indent}{DIRECTIVE} noenter\n")
    path.write_text("".join(lines))


def main(argv: list[str]) -> int:
    arguments = [item for item in argv[1:] if not item.startswith("--")]
    writing = "--apply" in argv
    if len(arguments) != 1:
        print(__doc__)
        return 2

    root = Path(arguments[0]).expanduser()
    files = sorted(root.rglob("*.sh")) if root.is_dir() else [root]
    total = 0

    for path in files:
        proposed = suggestions(path.read_text())
        if not proposed:
            continue
        total += len(proposed)
        print(f"\n{path.name}")
        for number, text in proposed:
            print(f"  {number:>4}: {text!r}")
        if writing:
            apply(path, proposed)

    print(
        f"\n{total} suggestion(s)"
        + (" applied" if writing else "; re-run with --apply to insert them")
    )
    print(
        "Review each one: this reads line shape only, and cannot tell whether a "
        "line is inside an editor."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
