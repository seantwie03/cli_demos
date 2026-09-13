"""A full-height command list with inline notes and a scrollable overflow view."""

from __future__ import annotations

import re
import shutil
import unicodedata
from dataclasses import dataclass

from .controller import Cursor
from .engine import Step

CLEAR = "\033[2J\033[H"
RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
ACCENT = "\033[36m"
NOTE = "\033[33m"
ALARM = "\033[1;31m"
DANGEROUS = re.compile(
    r"\b(rm\s+-[rf]|rm\s+-\w*[rf]|dd\s|mkfs|shred|>\s*/dev/|chown\s+-R|chmod\s+-R)"
)


def columns(text: str) -> int:
    return sum(
        (
            0
            if unicodedata.combining(c)
            else 2 if unicodedata.east_asian_width(c) in {"W", "F"} else 1
        )
        for c in text
    )


def _prefix(text: str, width: int) -> str:
    result = ""
    used = 0
    for char in text:
        size = columns(char)
        if used + size > width:
            break
        result += char
        used += size
    return result


def _fit(text: str, width: int) -> str:
    text = text.expandtabs(4)
    if width <= 0:
        return ""
    return text if columns(text) <= width else _prefix(text, width - 1) + "…"


def _wrap(text: str, width: int) -> list[str]:
    """Wrap without discarding note text, whitespace, or explicit line breaks."""
    result = []
    for line in text.expandtabs(4).split("\n"):
        while columns(line) > width:
            part = _prefix(line, width)
            if not part:  # A window narrower than one wide character.
                part = line[0]
            space = part.rfind(" ")
            if space > 0:
                part = part[: space + 1]
            result.append(part)
            line = line[len(part) :]
        result.append(line)
    return result


def action(step: Step) -> str:
    if step.kind == "header":
        return "[CLEAR+SHOW]" if step.clears else "[SHOW]"
    return {"arm": "[TYPE]", "run": "[ENTER]", "send": "[SEND]", "end": "[END]"}[
        step.kind
    ]


def title(step: Step) -> str:
    return "HEADER: " + step.label if step.kind == "header" else step.label


@dataclass
class Frame:
    text: str
    scroll: int
    page_size: int


def render(
    cursor: Cursor,
    *,
    name: str,
    recording: str | None = None,
    scroll: int = 0,
    size: tuple[int, int] | None = None,
) -> Frame:
    width, height = size or shutil.get_terminal_size((100, 30))
    width, height = max(1, width), max(1, height)
    step = cursor.steps[cursor.index]
    status = (
        f"{name} · item {cursor.item + 1}/{len(cursor.stops)} · line {step.line or '—'}"
    )
    if recording is not None:
        status += f" · REC {recording}"
    if not cursor.finished and DANGEROUS.search(step.text):
        status += " · Destructive; check before advancing"
    header = [DIM + _fit(status, width) + RESET]
    if height >= 5:
        header.append(DIM + "─" * width + RESET)
    footer = (
        "F1 back · F2 execute · F3 forward · PgUp/PgDn notes · Ctrl-C exit"
    )
    footer_rows = 1 if height >= 3 else 0
    budget = max(1, height - len(header) - footer_rows)

    if cursor.finished:
        message = [
            "Demo complete.",
            "Presentation remains live for questions.",
            "F2 returns to your shell; F1 revisits the last item.",
        ]
        if recording is not None:
            message = ["Playback complete. Finalizing recording…"]
        body = [_fit(line, width) for line in message[:budget]]
        offset, page_size = 0, budget
    else:
        # The left action column marks selection; keep command text aligned
        # across rows and phases. Narrow windows prioritize the next action.
        label = action(step)
        label_width = 13  # Longest label plus its separating space.
        content_width = max(0, width - label_width)

        def group(position: int) -> list[str]:
            item = cursor.steps[cursor.stops[position]]
            selected = position == cursor.item
            rows = []
            note_indent = " " * label_width if width >= label_width + 10 else ""
            note_prefix = (
                note_indent + "NOTE: " if width >= 8 else ""
            )
            note_width = max(1, width - len(note_prefix))
            for note in item.notes:
                for number, line in enumerate(_wrap(note, note_width)):
                    prefix = note_prefix if number == 0 else " " * len(note_prefix)
                    rows.append(NOTE + prefix + line + RESET)
            text = _fit(title(item), content_width)
            row = (label if selected else "").ljust(label_width) + text
            if width < label_width:
                row = _fit(label if selected else title(item), width)
            color = (
                ALARM
                if selected and DANGEROUS.search(item.text)
                else BOLD if selected else ACCENT if item.kind == "header" else DIM
            )
            rows.append(color + row + RESET)
            return rows

        first = max(0, cursor.item - 5)
        last = min(len(cursor.stops), cursor.item + 6)
        groups = [group(i) for i in range(first, last)]
        total = sum(map(len, groups))
        while total > budget and first < cursor.item:
            total -= len(groups.pop(0))
            first += 1
        while total > budget and last > cursor.item + 1:
            total -= len(groups.pop())
            last -= 1
        rows = [line for entry in groups for line in entry]
        if len(rows) > budget:
            # Only the selected group remains. Pin its command row while all
            # note lines stay reachable through the scrolling body.
            pinned = [rows[-1]] if budget >= 2 else []
            notes = rows[:-1]
            page_size = max(1, budget - len(pinned))
            offset = min(max(0, scroll), max(0, len(notes) - page_size))
            body = pinned + notes[offset : offset + page_size]
            footer = f"Notes {offset + 1}–{min(len(notes), offset + page_size)}/{len(notes)} · PgUp/PgDn scroll · F2 execute"
        else:
            body, offset, page_size = rows, 0, budget

    lines = header + body + [""] * max(0, budget - len(body))
    if footer_rows:
        lines.append(DIM + _fit(footer, width) + RESET)
    # Absolute placement avoids a trailing newline scrolling the full screen.
    screen = CLEAR + "".join(
        f"\033[{i + 1};1H{line}" for i, line in enumerate(lines[:height])
    )
    return Frame(screen, offset, page_size)
