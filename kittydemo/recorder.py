"""Private recorder supervisor, launched as the Presentation's process.

The outer PTY exists before `start` is published, preserving snapshot discovery.
Only a waited-for asciinema exit can produce a successful completion receipt.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time

#: Seconds a stop request gives the recorded shell to exit on its own.
GRACEFUL_STOP = 10
#: Seconds SIGTERM gets before SIGKILL, once the graceful deadline passes.
TERMINATE_WAIT = 2
#: Worst case before a receipt is published either way, plus slack for the
#: 0.05s poll and the publish itself. Controllers must wait at least this long.
SHUTDOWN_BUDGET = GRACEFUL_STOP + TERMINATE_WAIT + 3


def publish(directory: Path, name: str, value) -> None:
    pending = directory / (name + ".pending")
    pending.write_text(json.dumps(value))
    pending.replace(directory / name)


def supervise(directory: Path, cast: Path) -> int:
    interrupted = 0

    def interrupt(signum, *_):
        nonlocal interrupted
        interrupted = signum

    for sig in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, interrupt)
    publish(directory, "ready", True)
    deadline = time.monotonic() + 30
    while not (directory / "start").exists():
        if interrupted or (directory / "stop").exists() or time.monotonic() > deadline:
            return 1
        time.sleep(.05)

    process = None
    shell_fd = None
    forced = False
    source = None
    error = None
    try:
        command = shlex.join([sys.executable, str(Path(__file__).resolve()), "shell", str(directory)])
        # No --return, deliberately: asciinema must exit on its own merits so a
        # zero status means "the cast was finalized". With --return it would
        # inherit the recorded shell's status, and a SIGHUP'd bash exits 129,
        # which would report every successful recording as a failure.
        process = subprocess.Popen([
            "asciinema", "rec", str(cast), "--overwrite", "--window-size", "120x24",
            "--command", command,
        ])
        stop_deadline = None
        while process.poll() is None:
            if shell_fd is None and (directory / "shell").exists():
                pid = json.loads((directory / "shell").read_text())
                # A pidfd pins the process identity even if its PID is later reused.
                shell_fd = os.pidfd_open(pid)
                publish(directory, "running", True)
            if interrupted or (directory / "stop").exists():
                if stop_deadline is None:
                    # Say WHY we are stopping. A signal here means the
                    # Presentation was closed, which truncates the recording;
                    # only a controller stop may go on to publish a cast.
                    source = ("stop-file" if (directory / "stop").exists()
                              else signal.Signals(interrupted).name)
                    stop_deadline = time.monotonic() + GRACEFUL_STOP
                if shell_fd is not None:
                    try:
                        signal.pidfd_send_signal(shell_fd, signal.SIGHUP)
                    except ProcessLookupError:
                        pass
                    os.close(shell_fd)
                    shell_fd = None
                    # Do not reopen an already signalled shell PID.
                    (directory / "shell").unlink(missing_ok=True)
                if time.monotonic() >= stop_deadline:
                    forced = True
                    process.terminate()
                    try:
                        process.wait(timeout=TERMINATE_WAIT)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    break
            time.sleep(.05)
        returncode = process.wait()
    except Exception as exc:
        error = str(exc)
        forced = True
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        returncode = process.returncode if process else None
    finally:
        if shell_fd is not None:
            os.close(shell_fd)
    publish(directory, "finished", dict(returncode=returncode, source=source,
                                        forced=forced, error=error))
    # The receipt is the verdict; this exit status goes to Kitty and is discarded.
    # Returning closes the Presentation, which the controller then verifies.
    return 0


def main() -> int:
    mode, directory, *rest = sys.argv[1:]
    directory = Path(directory)
    if mode == "shell":
        publish(directory, "shell", os.getpid())
        deadline = time.monotonic() + 10
        while not (directory / "running").exists():
            if time.monotonic() >= deadline:
                return 1
            time.sleep(.05)
        os.execvp("bash", ["bash", "-l", "-i"])
    return supervise(directory, Path(rest[0]))


if __name__ == "__main__":
    raise SystemExit(main())
