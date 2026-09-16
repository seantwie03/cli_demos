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
    Steps advance on a timer into a sanitized Bash session. A supervisor waits
    for asciinema to finish before the Presentation closes and the cast is published.

Only one controller runs at a time. Presentation operations use the ID returned
by Kitty; a unique per-run marker also identifies a launch whose reply is lost.
"""

from __future__ import annotations

import json
import os
import select
import signal
import shutil
import subprocess
import sys
import termios
import time
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from .engine import SENTINEL, Step
from .placement import Placement
from .recorder import SHUTDOWN_BUDGET

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


class RecordingError(RuntimeError):
    """Recording startup or finalization could not be verified."""


class KittyConnectionError(RuntimeError):
    """Kitty could not provide a usable remote-control response."""


def kitty(*arguments: str, check: bool = True, input: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["kitty", "@", *arguments], check=check, capture_output=True, text=True, timeout=5,
        input=input,
    )


def _windows() -> list[dict]:
    """Every Kitty window; failed requests must not look like an empty instance."""
    endpoint = os.environ.get("KITTY_LISTEN_ON")
    target = (
        f"Kitty at KITTY_LISTEN_ON={endpoint!r}"
        if endpoint else
        "Kitty via the controlling terminal (outside Kitty, set KITTY_LISTEN_ON "
        "to the intended instance's socket address)"
    )
    try:
        listing = kitty("ls")
    except OSError as error:
        raise KittyConnectionError(f"Could not invoke kitty for {target}: {error}") from error
    except subprocess.TimeoutExpired as error:
        raise KittyConnectionError(
            f"Timed out after {error.timeout}s reaching {target}"
        ) from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or "").strip() or f"exit status {error.returncode}"
        raise KittyConnectionError(f"Could not reach {target}: {detail}") from error
    try:
        tree = json.loads(listing.stdout)
        if not isinstance(tree, list):
            raise ValueError("expected a list of OS windows")
        windows = []
        for entry in tree:
            if not isinstance(entry, dict) or not isinstance(entry.get("tabs"), list):
                raise ValueError("expected an OS window with a tabs list")
            for tab in entry["tabs"]:
                if not isinstance(tab, dict) or not isinstance(tab.get("windows"), list):
                    raise ValueError("expected a tab with a windows list")
                if any(not isinstance(window, dict) for window in tab["windows"]):
                    raise ValueError("expected window objects")
                windows.extend(tab["windows"])
        return windows
    except (ValueError, TypeError) as error:
        raise KittyConnectionError(f"Invalid window listing from {target}: {error}") from error


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

    Retain the existing single-presentation policy while controller key mappings
    and PID-file locking remain title-based. Presentation effects themselves use
    the owned window ID. Live mode deliberately leaves its window for questions.
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

    tty_path: Path | None = None
    window_id: int | None = None
    app_id: str = ""
    control: Path | None = None
    stopped_at: float | None = None

    @property
    def match(self) -> str:
        if self.window_id is None:
            raise RuntimeError("Presentation window identity is unavailable")
        return f"id:{self.window_id}"

    def request_stop(self) -> None:
        """Ask the supervisor to stop, starting the shared shutdown clock once."""
        if self.stopped_at is None:
            (self.control / "stop").touch()
            self.stopped_at = time.monotonic()

    def shutdown_left(self) -> float:
        """What is left of the recorder's own shutdown budget."""
        if self.stopped_at is None:
            return SHUTDOWN_BUDGET
        return max(0.0, SHUTDOWN_BUDGET - (time.monotonic() - self.stopped_at))

    def receipt(self):
        if self.control and (self.control / "finished").exists():
            return json.loads((self.control / "finished").read_text())
        return None

    def check_recording(self):
        receipt = self.receipt()
        if self.control and receipt is not None:
            raise RecordingError(f"Recorder exited before playback/finalization completed: {receipt}")

    def present(self):
        """Whether Kitty lists the owned window; None when it could not answer.

        A failed listing is not evidence the Presentation is gone, so callers
        using this as a safety net must never read None as absence.
        """
        try:
            return any(window.get("id") == self.window_id for window in _windows())
        except KittyConnectionError as error:
            print(f"warning: could not check the Presentation: {error}", file=sys.stderr)
            return None

    def wait_file(self, name: str, timeout: float = 10):
        deadline = time.monotonic() + timeout
        listed = 0.0
        while True:
            # Check the receipt first and on every pass: it is a stat, and it
            # must still win when a slow listing has overrun the deadline.
            path = self.control / name
            if path.exists():
                return json.loads(path.read_text())
            if name != "finished":
                self.check_recording()
            now = time.monotonic()
            if now >= deadline:
                raise RecordingError(f"Timed out waiting for recorder {name}")
            # A listing costs a Kitty round-trip; the receipt does not. Poll the
            # expensive check about once a second so it cannot dominate the loop.
            if now - listed >= 1:
                listed = now
                if self.present() is False:
                    raise RecordingError(f"Presentation closed while waiting for recorder {name}")
            time.sleep(.1)

    def close_window(self):
        # If the launch reply was lost, recover only this run's unique marker.
        if self.window_id is None:
            matches = [w for w in _windows() if w.get("user_vars", {}).get("kitty_demo") == self.app_id]
            if len(matches) > 1:
                raise RuntimeError("Ambiguous owned Presentation windows; refusing cleanup")
            if not matches:
                return
            self.window_id = matches[0]["id"]
        if any(w.get("id") == self.window_id for w in _windows()):
            kitty("close-window", "--match", self.match)
        deadline = time.monotonic() + 5
        while any(w.get("id") == self.window_id for w in _windows()):
            if time.monotonic() >= deadline:
                raise RecordingError("Presentation did not close")
            # Each pass is a Kitty round-trip; closure does not need 10Hz.
            time.sleep(.25)

    def dispose(self):
        if self.control:
            shutil.rmtree(self.control)
            self.control = None

    def abort(self):
        if self.control:
            self.request_stop()
            # Before start the supervisor has no child and can just be closed.
            if (self.control / "start").exists() and self.receipt() is None:
                try:
                    # Only what stop_recording left unspent; never a fresh budget.
                    self.wait_file("finished", self.shutdown_left())
                except Exception as error:
                    print(f"warning: recorder cleanup: {error}; state retained at {self.control}", file=sys.stderr)
                    self.close_window()
                    return
        self.close_window()
        self.dispose()

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
    """Own the window throughout startup and roll back partial launches."""
    if record and cast is None:
        raise ValueError("record mode needs an output path")
    if record and (not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal")):
        raise RecordingError("Recording requires Linux pidfds and Python 3.9+")
    session = Session(app_id="kitty-demo-" + uuid.uuid4().hex)
    try:
        if record:
            session.control = Path(tempfile.mkdtemp(prefix="kitty-demo-record-"))
        with Placement(session.app_id) as placement:
            before = tty_paths()
            arguments = ["launch", "--type=os-window", f"--title={TITLE}",
                         "--spacing=margin=55", f"--os-window-class={session.app_id}",
                         "--var", f"kitty_demo={session.app_id}"]
            if record:
                arguments += ["--", "env", "KITTY_SHELL_INTEGRATION=disabled",
                              sys.executable, str(Path(__file__).with_name("recorder.py")),
                              "supervise", str(session.control), str(cast)]
            response = kitty(*arguments)
            try:
                session.window_id = int(response.stdout.strip())
                if session.window_id <= 0:
                    session.window_id = None
                    raise ValueError("non-positive window ID")
            except ValueError as error:
                raise KittyConnectionError("Kitty launch returned an invalid window ID") from error
            placement.finish()
            if record:
                session.wait_file("ready")
                windows = [w for w in _windows() if w.get("id") == session.window_id]
                outer = _terminal_of(windows[0].get("pid", -1)) if windows else None
                before = tty_paths()
                if outer is None or outer not in before:
                    raise RecordingError("could not identify the outer presentation terminal")
                (session.control / "start").touch()
                session.wait_file("running")
            # Preserve snapshot selection; retry only an empty difference.
            deadline = time.monotonic() + 5
            while not (tty_paths() - before) and time.monotonic() < deadline:
                if record:
                    session.check_recording()
                time.sleep(.1)
            session.tty_path = new_tty(before)
            if record:
                time.sleep(.5)  # Bash startup remains a timing assumption.
                session.check_recording()
                send_text("PS1='$ '; unset PROMPT_COMMAND PS0; clear", match=session.match)
                send_key("enter", match=session.match)
        return session
    except BaseException:
        try:
            session.abort()
        except Exception as cleanup:
            print(f"warning: startup cleanup failed: {cleanup}", file=sys.stderr)
        raise


def send_text(text: str, *, match: str = MATCH) -> None:
    """Send literal text without Kitty interpreting backslash escapes."""
    kitty("send-text", "--match", match, "--stdin", input=text)


def send_key(key: str, *, match: str = MATCH) -> None:
    kitty("send-key", "--match", match, "--", key)


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
    send_key("enter", match=session.match)


def perform(session: Session, step: Step) -> None:
    """Carry out one press."""
    session.check_recording()
    if step.kind == "header":
        if step.clears:
            send_text("clear", match=session.match)
            send_key("enter", match=session.match)
            time.sleep(0.2)
        draw_header(session, step.lines)
    elif step.kind == "arm":
        send_text(step.text, match=session.match)
    elif step.kind == "run":
        send_key("enter", match=session.match)
    elif step.kind == "send":
        send_text(step.text, match=session.match)
    elif step.kind == "key":
        send_key(step.text, match=session.match)
    elif step.kind == "end":
        send_text(SENTINEL, match=session.match)
        send_key("enter", match=session.match)


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


def stop_recording(session: Session) -> None:
    """End the recorded shell, wait for asciinema, then close the owned window."""
    session.check_recording()
    session.request_stop()
    receipt = session.wait_file("finished", session.shutdown_left())
    # "source" must be our own stop file: a signal-driven stop means the window
    # was closed under us, and that recording is truncated, not finished.
    if (receipt.get("returncode") != 0 or receipt.get("source") != "stop-file"
            or receipt.get("forced") is not False or receipt.get("error")):
        raise RecordingError(f"Recorder did not finalize successfully: {receipt}")
    session.close_window()
    session.dispose()


def teardown(record: bool, session: Session) -> None:
    if record:
        stop_recording(session)
