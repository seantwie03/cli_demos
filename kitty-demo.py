#!/usr/bin/env python3
"""Drive a command-line demonstration from a command file.

    kitty-demo.py path/to/foo-exercise.sh            # live, for class
    kitty-demo.py --record path/to/foo-exercise.sh   # unattended, writes a .cast
    kitty-demo.py --check path/to/foo-exercise.sh    # validate only

Live mode uses F1 to select backward, F2 to perform the selected action (Enter
sent to this window), and F3 to select forward through Kitty mappings.
Record mode advances on a timer into a sanitized session that
asciinema records, and writes the cast beside the command file.

Every mode validates the command file before it does anything else. A file that
cannot be parsed stops the run here, while no window is open, no session is
claimed, and nothing is recording. `--check` is that validation on its own.

Only one demonstration runs at a time. Starting a second one fails with a
message naming the window to close. Presentation commands and cleanup target
the window ID owned by this run.
"""

from __future__ import annotations

import argparse
import os
import tempfile
import subprocess
import sys
import time
from contextlib import nullcontext
from pathlib import Path

from kittydemo import driver, hud
from kittydemo.controller import Cursor
from kittydemo.engine import CommandFileError, parse


def report(path: Path, steps) -> int:
    """Confirm the file parsed, and say how many presses it will take."""
    print(f"{path.name}: {len(steps)} presses")
    return 0


def play(options, path: Path, steps, session: driver.Session) -> None:
    """Play sequentially, with selection and note scrolling in live mode."""
    cursor = Cursor(steps)
    scroll = 0
    started = time.monotonic()
    terminal = sys.stdout.isatty()
    try:
        if terminal:
            sys.stdout.write("\033[?1049h\033[?25l")
        with driver.Requests() if not options.record else nullcontext(None) as requests:
            while True:
                elapsed = time.strftime(
                    "%M:%S", time.gmtime(time.monotonic() - started)
                )
                frame = hud.render(
                    cursor,
                    name=path.name,
                    scroll=scroll,
                    recording=elapsed if options.record else None,
                )
                sys.stdout.write(frame.text)
                sys.stdout.flush()
                scroll = frame.scroll
                if options.record:
                    session.check_recording()
                    if cursor.finished:
                        time.sleep(options.pause)
                        return
                    request = "advance"
                else:
                    request = requests.wait()
                if request in {"back", "forward"}:
                    cursor.navigate(request)
                    scroll = 0
                elif request in {"scroll-up", "scroll-down"}:
                    direction = -1 if request == "scroll-up" else 1
                    scroll = max(0, scroll + direction * max(1, frame.page_size - 1))
                elif request == "resize":
                    scroll = 0
                elif request == "advance":
                    if cursor.finished:
                        return
                    step = steps[cursor.index]
                    driver.perform(session, step)
                    cursor.advanced()
                    scroll = 0
                    if options.record:
                        time.sleep(
                            step.pause if step.pause is not None else options.pause
                        )
    finally:
        if terminal:
            sys.stdout.write("\033[?25h\033[?1049l")
            sys.stdout.flush()


def run(options, path: Path, steps) -> int:
    """Launch a session, play it, and clean up whatever happened."""
    destination = partial = session = None
    try:
        if options.record:
            destination = path.with_suffix(".cast")
            descriptor, name = tempfile.mkstemp(prefix=destination.name + ".", suffix=".partial", dir=destination.parent)
            os.close(descriptor)
            partial = Path(name)
        session = driver.launch(record=options.record, cast=partial)
        play(options, path, steps, session)
        if options.record:
            driver.teardown(record=True, session=session)
            if partial.stat().st_size == 0:
                raise driver.RecordingError("Recorder produced an empty file")
            with partial.open("rb") as recording:
                os.fsync(recording.fileno())
            os.replace(partial, destination)
            print(f"\nRecording written to {destination}")
        return 0
    except BaseException:
        if options.record and session is not None:
            try:
                session.abort()
            except Exception as cleanup:
                print(f"warning: recording cleanup failed: {cleanup}", file=sys.stderr)
        if partial is not None and partial.exists():
            print(f"Incomplete recording retained at {partial}", file=sys.stderr)
        raise


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command_file", help="the command file to play")
    parser.add_argument(
        "--record",
        action="store_true",
        help="play unattended into an asciinema recording",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=driver.DEFAULT_PAUSE,
        help="record-mode seconds between steps (default: %(default)s)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the command file without running anything",
    )
    options = parser.parse_args(argv)

    if options.pause < 0 or options.pause != options.pause:
        raise SystemExit("--pause needs a finite, non-negative number of seconds")

    path = Path(options.command_file).expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"No such command file: {path}")

    source = path.read_text()
    try:
        steps = parse(source)
    except CommandFileError as error:
        raise SystemExit(f"{path.name}: {error}") from error

    if options.check:
        return report(path, steps)

    try:
        driver.claim_session()
    except driver.SessionInUse as conflict:
        raise SystemExit(str(conflict)) from conflict

    try:
        driver.claim_controller_window()
        return run(options, path, steps)
    finally:
        failed = sys.exc_info()[0] is not None
        cleanup_error = None
        for cleanup in (driver.release_controller_window, driver.release_session):
            try:
                cleanup()
            except Exception as error:
                if failed or cleanup_error is not None:
                    print(f"warning: controller cleanup failed: {error}", file=sys.stderr)
                else:
                    cleanup_error = error
        if cleanup_error is not None:
            raise cleanup_error


def main(argv: list[str]) -> int:
    try:
        return _main(argv)
    except (driver.KittyConnectionError, driver.RecordingError, OSError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nDemo interrupted.", file=sys.stderr)
        return 130
    except EOFError:
        print("\nController input closed; demo stopped.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
