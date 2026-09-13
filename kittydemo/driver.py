"""Play a parsed command file through two kitty windows.

The presentation window is what the audience sees and stays a fully live
terminal throughout, so a question can always be answered with an ad-hoc
command. The controller window shows the instructor what the next press will
do and carries the notes the audience never sees.

Two modes share one step sequence:

live
    The instructor advances. Nothing closes at the end, because the
    demonstration is usually followed by questions that need the terminal.

record
    Steps advance on a timer into a sanitized session that asciinema is
    recording. At the end the presentation window is closed, which stops the
    recording cleanly and never returns to the local shell.

Only one demonstration may run at a time. Both windows are addressed by a
fixed title, and kitty applies a remote-control command to every window that
matches, so a second session would let commands reach the previous
demonstration's window and would split the advance key between two
controllers. Refusing to start is simpler than telling two sessions apart, and
it needs no change to the instructor's `kitty.conf`.
"""

from __future__ import annotations

import json
import os
import shlex
import select
import shutil
import subprocess
import sys
import termios
import time
from dataclasses import dataclass
from pathlib import Path

from .engine import SENTINEL, Step

TITLE = "Presentation"
MATCH = f"title:^{TITLE}$"
CONTROLLER_TITLE = "Controller"

RESET = "\033[0m"
HEADER_COLOR = "\033[1;34m"

#: Seconds record mode holds after a step with no explicit `#@ pause`.
DEFAULT_PAUSE = 3.0

STATE_DIR = Path.home() / ".cache" / "kitty-demo"
CONTROLLER_PID = STATE_DIR / "controller.pid"


class SessionInUse(RuntimeError):
    """Another demonstration is already running."""


def kitty(*arguments: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["kitty", "@", *arguments], check=check, capture_output=True, text=True
    )


def _windows() -> list[dict]:
    """Every kitty window, or an empty list if kitty cannot be reached."""
    try:
        listing = kitty("ls")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    try:
        tree = json.loads(listing.stdout or "[]")
    except json.JSONDecodeError:
        return []
    return [
        window
        for entry in tree
        for tab in entry.get("tabs", [])
        for window in tab.get("windows", [])
    ]


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def claim_session() -> None:
    """Refuse to start when a demonstration is already running.

    Both windows are checked, because a duplicate of either breaks a different
    thing: a second presentation window receives commands meant for this
    session, and a second controller splits the advance key between them.

    Live mode leaves its presentation window open on purpose, so this fires
    routinely between back-to-back demonstrations. The message therefore has to
    say what to close rather than merely report a conflict.
    """
    if any(window.get("title") == TITLE for window in _windows()):
        raise SessionInUse(
            f"A {TITLE!r} window from an earlier demonstration is still open.\n"
            f"Close it (ctrl+alt+w with it focused), then start again."
        )

    if CONTROLLER_PID.exists():
        try:
            previous = int(CONTROLLER_PID.read_text().strip())
        except ValueError:
            previous = None
        if (
            previous is not None
            and previous != os.getpid()
            and _process_alive(previous)
        ):
            raise SessionInUse(
                f"Another controller is already running (pid {previous}).\n"
                f"Finish or close that demonstration, then start again."
            )

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    CONTROLLER_PID.write_text(f"{os.getpid()}\n")


def release_session() -> None:
    """Give up this session's claim, ignoring one we no longer own."""
    try:
        if int(CONTROLLER_PID.read_text().strip()) == os.getpid():
            CONTROLLER_PID.unlink()
    except (FileNotFoundError, ValueError):
        pass


@dataclass
class Session:
    """The presentation window and the pseudo-terminal inside it."""

    tty_path: Path

    @property
    def width(self) -> int:
        try:
            size = subprocess.run(
                ["stty", "-F", str(self.tty_path), "size"],
                capture_output=True,
                text=True,
                check=True,
            )
            return int(size.stdout.split()[1])
        except (subprocess.CalledProcessError, IndexError, ValueError):
            return 120

    def write(self, text: str) -> None:
        with self.tty_path.open("w") as handle:
            handle.write(text)


def _terminal_of(pid: int) -> Path | None:
    """The pseudo-terminal a process reads from, if it can be determined."""
    try:
        target = Path(f"/proc/{pid}/fd/0").resolve()
    except OSError:
        return None
    return target if target.parent == Path("/dev/pts") else None


def tty_paths() -> set[Path]:
    """Snapshot numeric PTY devices, excluding entries such as ptmx."""
    return {path for path in Path("/dev/pts").iterdir() if path.name.isdigit()}


def new_tty(before: set[Path]) -> Path:
    """Select exactly one new PTY; concurrent terminal creation is ambiguous."""
    created = tty_paths() - before
    if len(created) != 1:
        raise RuntimeError(
            f"Expected one new presentation TTY, found {len(created)}; "
            "retry without opening other terminals during startup"
        )
    return created.pop()


def launch(record: bool, cast: Path | None) -> Session:
    """Open the presentation window and find the terminal inside it."""
    if record and cast is None:
        raise ValueError("record mode needs an output path")
    before = tty_paths()
    arguments = [
        "launch",
        "--type=os-window",
        f"--title={TITLE}",
        "--spacing=margin=55",
    ]
    if record:
        # Record into a plain shell, so the recording shows a terminal a
        # student could reproduce rather than one carrying kitty's own prompt
        # marks and cursor changes. `--env` cannot turn this off: kitty sets
        # the variable itself from its configuration after applying `--env`,
        # so it comes back as "enabled". Launching the shell through `env`
        # sets it last and therefore wins.
        shell = os.environ.get("SHELL", "/bin/bash")
        arguments += ["--", "env", "KITTY_SHELL_INTEGRATION=disabled", shell, "-l"]
    kitty(*arguments)

    if os.environ.get("XDG_CURRENT_DESKTOP") == "niri":
        time.sleep(1)
        helper = (
            Path(__file__).resolve().parent.parent / "niri-maximize_on_other_monitor.sh"
        )
        if helper.exists():
            listing = subprocess.run(
                ["niri", "msg", "--json", "windows"],
                capture_output=True,
                text=True,
            )
            for window in json.loads(listing.stdout or "[]"):
                if window.get("title") == TITLE:
                    subprocess.run([str(helper), str(window["id"])], check=False)
                    break

    if record:
        # Snapshot only after the outer PTY exists, so the recorder's inner
        # PTY is the one new device. Kitty's foreground processes cannot
        # identify that inner terminal because it has its own process group.
        time.sleep(0.5)
        windows = [window for window in _windows() if window.get("title") == TITLE]
        outer = _terminal_of(windows[0].get("pid", -1)) if windows else None
        before = tty_paths()
        if outer is None or outer not in before:
            raise RuntimeError("could not identify the outer presentation terminal")
        # Quote the destination. It comes from a command-file path, and a
        # course checked out under a directory containing a space would
        # otherwise split into several shell arguments.
        send_text(
            f"asciinema rec {shlex.quote(str(cast))} "
            "--overwrite --window-size 120x24"
        )
        send_key("enter")
        time.sleep(1.5)
        # systemd's OSC context hooks the shell in two places and both have to
        # go: `PROMPT_COMMAND+=(__systemd_osc_context_precmdline)` after each
        # command, and `PS0` before each one. Its sequence carries the machine
        # ID, the username, and the hostname. `unset` rather than assignment,
        # because bash keeps PROMPT_COMMAND as an array and assigning would
        # replace only its first element, leaving the rest running.
        send_text("PS1='$ '; unset PROMPT_COMMAND PS0; clear")
        send_key("enter")

    time.sleep(0.5)
    return Session(tty_path=new_tty(before))


def send_text(text: str) -> None:
    kitty("send-text", "--match", MATCH, "--", text)


def send_key(key: str) -> None:
    kitty("send-key", "--match", MATCH, "--", key)


def draw_header(session: Session, lines: tuple[str, ...]) -> None:
    """Paint a section header across the presentation terminal.

    Each line is padded out to the terminal width instead of ending with a
    newline. Writing a newline to another process's terminal does not reliably
    start a new line over SSH, but filling the row does, because the terminal
    wraps.
    """
    width = session.width
    border = "#" * width

    def line(text: str) -> None:
        session.write(f"{HEADER_COLOR}{text}{RESET}")
        padding = width - len(text)
        if padding > 0:
            session.write(" " * padding)

    session.write("\r")
    line("")
    line(border)
    line(f"    {lines[0]}")
    for extra in lines[1:]:
        line(f"        {extra}")
    line(border)
    send_key("enter")


def perform(session: Session, step: Step) -> None:
    """Carry out one press."""
    if step.kind == "header":
        if step.clears:
            send_text("clear")
            send_key("enter")
            time.sleep(0.2)
        draw_header(session, step.lines)
    elif step.kind == "arm":
        send_text(step.text)
    elif step.kind == "run":
        send_key("enter")
    elif step.kind == "send":
        send_text(step.text)
    elif step.kind == "key":
        send_key(step.text)
    elif step.kind == "end":
        send_text(SENTINEL)
        send_key("enter")


class Requests:
    """Read mapping requests without echo, preserving Ctrl-C and resize events."""

    def __init__(self) -> None:
        self.descriptor = sys.stdin.fileno()
        self.saved = None
        self.buffer = b""
        self.size = shutil.get_terminal_size()

    def __enter__(self):
        if os.isatty(self.descriptor):
            self.saved = termios.tcgetattr(self.descriptor)
            settings = termios.tcgetattr(self.descriptor)
            settings[0] |= termios.ICRNL
            settings[3] |= termios.ICANON | termios.ISIG
            settings[3] &= ~(termios.ECHO | termios.ECHONL)
            termios.tcsetattr(self.descriptor, termios.TCSANOW, settings)
        return self

    def __exit__(self, *exc):
        if self.saved is not None:
            termios.tcsetattr(self.descriptor, termios.TCSANOW, self.saved)

    def wait(self) -> str:
        while True:
            size = shutil.get_terminal_size()
            if size != self.size:
                self.size = size
                return "resize"
            if b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                request = line.decode("utf-8", errors="replace").rstrip("\r")
                if request == "":
                    return "advance"
                if request in {"back", "forward", "scroll-up", "scroll-down"}:
                    return request
                continue
            if select.select([self.descriptor], [], [], 0.2)[0]:
                chunk = os.read(self.descriptor, 4096)
                if not chunk:
                    raise EOFError
                self.buffer += chunk


def claim_controller_window() -> None:
    """Name this window so the advance key can find it.

    The kitty mapping that advances a demonstration sends Enter to
    `title:Controller`. Naming the window here rather than relying on the
    launch command means the script works when started by hand from any
    terminal, not only from a mapping that passes `--title`.

    The title is pushed onto the terminal's title stack first so it can be put
    back on the way out, leaving the window as it was found.
    """
    sys.stdout.write(f"\033[22;2t\033]2;{CONTROLLER_TITLE}\007")
    sys.stdout.flush()


def release_controller_window() -> None:
    """Restore the title this window had before the demonstration."""
    sys.stdout.write("\033[23;2t")
    sys.stdout.flush()


def stop_recording() -> None:
    """Close the presentation window, which ends the recording cleanly.

    kitty sends SIGHUP, and asciinema writes its events as they happen, so the
    cast is complete and well formed. Closing the window also keeps the local
    shell out of the recording entirely, because the session never returns to
    it.
    """
    kitty("close-window", "--match", MATCH, check=False)


def teardown(record: bool) -> None:
    """End the demonstration.

    Live mode closes nothing: the demonstration is normally followed by
    questions, and the presentation window is the only place to answer them.
    """
    if record:
        stop_recording()
