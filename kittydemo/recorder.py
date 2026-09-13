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


def publish(directory: Path, name: str, value) -> None:
    pending = directory / (name + ".pending")
    pending.write_text(json.dumps(value))
    pending.replace(directory / name)


def supervise(directory: Path, cast: Path) -> int:
    interrupted = False

    def interrupt(*_):
        nonlocal interrupted
        interrupted = True

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
    requested = forced = False
    error = None
    try:
        command = shlex.join([sys.executable, str(Path(__file__).resolve()), "shell", str(directory)])
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
                    requested = True
                    stop_deadline = time.monotonic() + 10
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
                        process.wait(timeout=2)
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
    publish(directory, "finished", dict(returncode=returncode, requested=requested,
                                        forced=forced, error=error))
    deadline = time.monotonic() + 20
    while not interrupted and not (directory / "release").exists() and time.monotonic() < deadline:
        time.sleep(.05)
    return 0 if returncode == 0 and requested and not forced else 1


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
