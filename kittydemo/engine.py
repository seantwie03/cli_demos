"""Turn a command file into the sequence of steps one keypress each advances.

The engine is pure: it reads text and returns data. Everything that talks to a
terminal lives in the driver, so every rule about how a demonstration advances
can be tested without a running kitty.

A *step* is exactly what one press of the advance key does. Two rules shape the
sequence and both exist to remove decisions from the instructor's hands during
a live class:

* A presenter note never costs a press. It is attached to the step that follows
  it, and the HUD decides whether to show it before or alongside that step.
* A bare ``clear`` immediately followed by a section header is one press. A
  blank screen with nothing on it is not a teaching moment.

Command file syntax::

    #^ Section header          drawn full width in the presentation window
    #  header continuation     audience visible, inside a header block only
    #! presenter note          controller only, attaches to the next step
    #@ directive               engine instruction, never displayed
    anything else              typed into the presentation window

A ``#`` line reads two ways, and the preceding step decides which. After a
section header it is audience-visible header text, and so is every ``#`` line
after that, however the block is spaced. After a command it is a line to type,
like any other: a shell comment the audience is meant to read, or a comment
going into a config file under an editor. A command is what closes a section
header and makes a comment typeable again.

Blank lines are invisible throughout. The corpus writes ``clear``, a blank
line, then a header hundreds of times, and a parser that read blanks as
structure would turn each of those one-press transitions into three.

Directives::

    #@ pause N     hold N seconds after the next step (record mode only)
    #@ noenter     the next line is keystrokes, so send no Enter after it
    #@ key KEY     send one Kitty key specification, without extra Enter

Every line gets an Enter unless it says otherwise. That is right at a shell
prompt and right for most keystrokes inside an editor too, because there the
Enter is the newline: a body line being inserted needs one, and so does
``:wq`` after leaving insert mode with ``#@ key escape``.
Only keystrokes that act the moment they arrive, such as ``q`` in a
pager or ``dd`` in vim, must not get one, and those are the lines to mark.

Nothing here tries to work out where a full-screen program begins or ends.
Doing so needs a heuristic that is wrong often enough to be worse than the
default, and the default is already correct for the large majority of lines.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

HEADER = "#^"
CONTINUATION = "#"
NOTE = "#!"
DIRECTIVE = "#@"

#: What the driver types once the command file is exhausted. It is the
#: instructor's cue that the demonstration is over and the cut point the cast
#: post-processor trims to, so it must not change without updating that script.
SENTINEL = "# End"

DIRECTIVES = frozenset({"pause", "noenter", "key"})


def strip_marker(text: str, marker: str) -> str:
    """Remove a sigil and at most one space, keeping the rest verbatim.

    Header continuation lines carry their own indentation, and that
    indentation is what shows the reader which lines are requirements and
    which are the tasks under them. Stripping all leading whitespace would
    flatten that hierarchy, so only the sigil and a single separating space
    come off.
    """
    body = text.lstrip()[len(marker) :]
    return body[1:] if body.startswith(" ") else body


class CommandFileError(ValueError):
    """A command file could not be understood."""


@dataclass(frozen=True)
class Step:
    """One press of the advance key."""

    #: ``header`` draws a section header, ``arm`` puts a command on the prompt,
    #: ``run`` executes what is on the prompt, ``send`` types keystrokes that
    #: need no Enter, ``key`` sends a key event, and ``end`` is the terminal step.
    kind: str
    text: str = ""
    #: Audience-visible header lines, for ``header`` steps.
    lines: tuple[str, ...] = ()
    #: Presenter notes, shown only in the controller window.
    notes: tuple[str, ...] = ()
    #: Seconds to hold after this step in record mode. ``None`` means default.
    pause: float | None = None
    #: A merged bare ``clear`` runs before this header is drawn.
    clears: bool = False
    #: 1-based line in the command file, for HUD display and error messages.
    line: int = 0

    @property
    def label(self) -> str:
        """A short description of what this press will do."""
        if self.kind == "header":
            return self.lines[0].strip() if self.lines else "Section"
        if self.kind == "end":
            return SENTINEL
        return self.text


@dataclass
class _Pending:
    """Notes and directives waiting to attach to the next step."""

    notes: list[str] = field(default_factory=list)
    pause: float | None = None
    #: Set by ``#@ noenter``: the next command takes no Enter.
    noenter: bool = False
    #: Line the directive was written on, for error messages.
    noenter_line: int = 0
    #: Line a pause was written on, for error messages.
    pause_line: int = 0
    clears: bool = False

    def reset(self) -> None:
        self.notes.clear()
        self.pause = None
        self.noenter = False
        self.noenter_line = 0
        self.pause_line = 0
        self.clears = False


def classify(line: str) -> str:
    """Name the role a raw line plays, ignoring indentation."""
    stripped = line.lstrip()
    if stripped.startswith(HEADER):
        return "header"
    if stripped.startswith(NOTE):
        return "note"
    if stripped.startswith(DIRECTIVE):
        return "directive"
    if stripped.startswith(CONTINUATION):
        return "continuation"
    return "command"


def directive_of(line: str) -> tuple[str, str]:
    """Split a directive line into its name and argument."""
    body = line.lstrip()[len(DIRECTIVE) :]
    parts = body.split(None, 1)
    name = parts[0] if parts else ""
    return name, (parts[1].strip() if len(parts) > 1 else "")


def _parse_directive(line: str, number: int) -> tuple[str, str]:
    name, argument = directive_of(line)
    if not name:
        raise CommandFileError(f"line {number}: empty {DIRECTIVE} directive")
    if name not in DIRECTIVES:
        raise CommandFileError(
            f"line {number}: unknown directive {name!r}; expected one of "
            + ", ".join(sorted(DIRECTIVES))
        )
    return name, argument


def _parse_pause(argument: str, number: int) -> float:
    """Read a hold duration, refusing values that cannot be waited on."""
    try:
        seconds = float(argument)
    except ValueError as error:
        raise CommandFileError(
            f"line {number}: pause needs a number of seconds"
        ) from error
    if not math.isfinite(seconds):
        raise CommandFileError(
            f"line {number}: pause needs a finite number of seconds, not {argument!r}"
        )
    if seconds < 0:
        raise CommandFileError(
            f"line {number}: pause cannot be negative, got {argument!r}"
        )
    return seconds


def _significant(source: str) -> list[tuple[int, str]]:
    return [
        (number, text)
        for number, text in enumerate(source.splitlines(), start=1)
        if text.strip()
    ]


def parse(source: str) -> list[Step]:
    """Compile a command file into the steps the driver plays."""
    raw = _significant(source)

    steps: list[Step] = []
    pending = _Pending()
    index = 0

    def emit(step: Step) -> None:
        """Attach anything pending to the first step of a group."""
        steps.append(
            replace(step, notes=tuple(pending.notes)) if pending.notes else step
        )
        pending.notes.clear()

    def refuse_stray_noenter(what: str) -> None:
        """`#@ noenter` may bind only to a command.

        It leaks otherwise. Written above a header, or above a bare `clear`
        that merges into one, it would carry past that construct and silently
        strip the Enter from the next real command, so the recording would show
        a command typed and never run.
        """
        if pending.noenter:
            raise CommandFileError(
                f"line {pending.noenter_line}: '{DIRECTIVE} noenter' must be "
                f"followed by a command, not {what}"
            )

    while index < len(raw):
        number, text = raw[index]
        role = classify(text)
        body = text.lstrip()

        if role == "note":
            # A note never costs a press; it rides along with the next step.
            pending.notes.append(body[len(NOTE) :].strip())
            index += 1
            continue

        if role == "directive":
            name, argument = _parse_directive(text, number)
            if name == "noenter":
                pending.noenter = True
                pending.noenter_line = number
            elif name == "key":
                if not argument:
                    raise CommandFileError(f"line {number}: key needs a key specification")
                refuse_stray_noenter("a key step (which already sends no extra Enter)")
                emit(Step(kind="key", text=argument, pause=pending.pause, line=number))
                pending.reset()
            else:
                pending.pause = _parse_pause(argument, number)
                pending.pause_line = number
            index += 1
            continue

        if role == "header":
            refuse_stray_noenter("a section header")
            lines = [strip_marker(body, HEADER)]
            index += 1
            # Every `#` line that follows belongs to this section, however it
            # is spaced. A comment is only typed once a command has intervened.
            while index < len(raw) and classify(raw[index][1]) == "continuation":
                lines.append(strip_marker(raw[index][1], CONTINUATION))
                index += 1
            emit(
                Step(
                    kind="header",
                    lines=tuple(lines),
                    clears=pending.clears,
                    pause=pending.pause,
                    line=number,
                )
            )
            pending.pause = None
            pending.pause_line = 0
            pending.clears = False
            continue

        # A bare `clear` whose next line opens a header block is merged into
        # that header, so the transition between sections costs one press. The
        # clear is only remembered here; the header branch performs it, which
        # keeps the merge intact when a note or directive sits between them.
        if body == "clear" and _opens_header(raw, index + 1):
            refuse_stray_noenter("a 'clear' that merges into a section header")
            pending.clears = True
            index += 1
            continue

        if pending.noenter:
            emit(Step(kind="send", text=body, pause=pending.pause, line=number))
        else:
            emit(Step(kind="arm", text=body, line=number))
            steps.append(
                Step(kind="run", text=body, pause=pending.pause, line=number)
            )
        pending.reset()
        index += 1

    # A directive that binds to nothing is a mistake worth reporting, because
    # silently discarding it hides an authoring error rather than fixing it.
    refuse_stray_noenter("the end of the file")
    if pending.pause is not None:
        raise CommandFileError(
            f"line {pending.pause_line}: '{DIRECTIVE} pause' must be followed by "
            "a step to hold after, but the file ends first"
        )

    if pending.notes:
        # Trailing notes would otherwise be lost, so the end step carries them.
        emit(Step(kind="end", text=SENTINEL))
    else:
        steps.append(Step(kind="end", text=SENTINEL))
    return steps


def _opens_header(raw: list[tuple[int, str]], index: int) -> bool:
    """Whether a header block starts here, ignoring anything invisible first.

    Notes and modifier directives can be part of the same section transition.
    A key directive is an action and prevents merging across it.
    """
    while index < len(raw) and classify(raw[index][1]) in {"directive", "note"}:
        if (
            classify(raw[index][1]) == "directive"
            and directive_of(raw[index][1])[0] == "key"
        ):
            return False
        index += 1
    return index < len(raw) and classify(raw[index][1]) == "header"
