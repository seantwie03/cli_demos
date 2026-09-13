"""Publication/rollback contracts and a real recorder under an isolated PTY."""
import io
import json
import os
from pathlib import Path
import pty
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch

from kittydemo import driver
from tests.test_controller import cli


class Publication(unittest.TestCase):
    def test_only_verified_finalization_replaces_previous_cast(self):
        for failure in (None, "launch", "play", "teardown", "replace"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "demo.sh"
                destination = path.with_suffix(".cast")
                destination.write_text("previous good cast")
                session = Mock()
                partials = []
                order = []

                def launch(**kwargs):
                    partials.append(kwargs["cast"])
                    kwargs["cast"].write_text("new recording")
                    if failure == "launch":
                        raise driver.RecordingError("launch failed")
                    return session

                def finalize(**kwargs):
                    order.append("finalize")
                    self.assertIs(kwargs["session"], session)
                    if failure == "teardown":
                        raise driver.RecordingError("finalization failed")

                replace = os.replace

                def publish(source, target):
                    self.assertEqual(order, ["finalize"])
                    if failure == "replace":
                        raise OSError("publication failed")
                    replace(source, target)

                with patch.object(driver, "launch", side_effect=launch), patch.object(
                    driver, "teardown", side_effect=finalize
                ), patch.object(cli, "play", side_effect=RuntimeError("play failed") if failure == "play" else None), patch.object(
                    cli.os, "replace", side_effect=publish
                ), redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()) as stderr:
                    if failure:
                        with self.assertRaises((RuntimeError, OSError)):
                            cli.run(SimpleNamespace(record=True), path, [])
                        self.assertEqual(destination.read_text(), "previous good cast")
                        self.assertEqual(partials[0].read_text(), "new recording")
                        self.assertIn(str(partials[0]), stderr.getvalue())
                        self.assertNotIn("Recording written", stdout.getvalue())
                        if failure != "launch":
                            session.abort.assert_called_once()
                    else:
                        self.assertEqual(cli.run(SimpleNamespace(record=True), path, []), 0)
                        self.assertEqual(destination.read_text(), "new recording")
                        self.assertFalse(partials[0].exists())
                        session.abort.assert_not_called()

    def test_retry_preserves_earlier_partial_and_original_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "demo.sh"
            old = path.with_suffix(".cast.partial")
            old.write_text("earlier evidence")
            session = Mock()
            session.abort.side_effect = OSError("cleanup failed")
            with patch.object(driver, "launch", return_value=session), patch.object(
                cli, "play", side_effect=KeyboardInterrupt
            ), redirect_stderr(io.StringIO()):
                for _ in range(2):
                    with self.assertRaises(KeyboardInterrupt):
                        cli.run(SimpleNamespace(record=True), path, [])
            self.assertEqual(old.read_text(), "earlier evidence")
            self.assertEqual(len(list(Path(directory).glob("*.partial"))), 3)

    def test_live_success_and_interruption_leave_window_open(self):
        for failure in (None, KeyboardInterrupt):
            session = Mock()
            with patch.object(driver, "launch", return_value=session), patch.object(cli, "play", side_effect=failure):
                if failure:
                    with self.assertRaises(failure):
                        cli.run(SimpleNamespace(record=False), Path("demo.sh"), [])
                else:
                    self.assertEqual(cli.run(SimpleNamespace(record=False), Path("demo.sh"), []), 0)
                session.abort.assert_not_called()


class Finalization(unittest.TestCase):
    def test_bad_receipts_and_close_failure_prevent_success(self):
        good = dict(returncode=0, requested=True, forced=False, error=None)
        for changes in ({"returncode": 7}, {"requested": False}, {"forced": True}, {"error": "failed"}, {}):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as directory:
                session = driver.Session(window_id=7, control=Path(directory))
                with patch.object(session, "wait_file", return_value=good | changes), patch.object(
                    session, "close_window", side_effect=OSError("close failed") if not changes else None
                ) as close:
                    with self.assertRaises((driver.RecordingError, OSError)):
                        driver.stop_recording(session)
                    self.assertTrue((Path(directory) / "stop").exists())
                    if changes:
                        close.assert_not_called()

    def test_early_exit_is_not_published_as_success(self):
        with tempfile.TemporaryDirectory() as directory:
            session = driver.Session(window_id=7, control=Path(directory))
            (session.control / "finished").write_text('{"returncode": 0}')
            with self.assertRaisesRegex(driver.RecordingError, "exited before"):
                driver.stop_recording(session)
            self.assertFalse((session.control / "stop").exists())

    def test_close_uses_owned_id_and_waits_for_disappearance(self):
        session = driver.Session(window_id=7)
        with patch.object(driver, "_windows", side_effect=[[{"id": 7}, {"id": 8}], [{"id": 8}]]), patch.object(driver, "kitty") as remote:
            session.close_window()
            remote.assert_called_once_with("close-window", "--match", "id:7")

    def test_lost_launch_reply_recovers_only_unique_marker(self):
        session = driver.Session(app_id="owned")
        windows = [{"id": 9, "user_vars": {"kitty_demo": "other"}},
                   {"id": 7, "user_vars": {"kitty_demo": "owned"}}]
        with patch.object(driver, "_windows", side_effect=[windows, windows, []]), patch.object(driver, "kitty") as remote:
            session.close_window()
            remote.assert_called_once_with("close-window", "--match", "id:7")

    def test_missing_receipt_has_a_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            session = driver.Session(window_id=7, control=Path(directory))
            with patch.object(driver, "_windows", return_value=[{"id": 7}]), patch.object(driver.time, "monotonic", side_effect=[0, 0, 2]), patch.object(driver.time, "sleep"):
                with self.assertRaisesRegex(driver.RecordingError, "Timed out"):
                    session.wait_file("finished", 1)


@unittest.skipUnless(shutil.which("asciinema") and hasattr(os, "pidfd_open"), "requires asciinema and Linux pidfds")
class RealRecorder(unittest.TestCase):
    def test_waited_exit_captures_header_on_snapshot_selected_inner_pty(self):
        with tempfile.TemporaryDirectory() as directory:
            control = Path(directory) / "control"
            control.mkdir()
            cast = Path(directory) / "demo.cast"
            pid, master = pty.fork()
            if pid == 0:
                os.execv(sys.executable, [sys.executable, str(Path(driver.__file__).with_name("recorder.py")), "supervise", str(control), str(cast)])
            reaped = False
            try:
                self.wait_file(control / "ready", master)
                outer = driver._terminal_of(pid)
                before = driver.tty_paths()
                (control / "start").touch()
                self.wait_file(control / "running", master)
                inner = driver.new_tty(before)
                self.assertNotEqual(inner, outer)
                marker = "UNIQUE_RECORDED_HEADER"
                driver.Session(tty_path=inner).write(marker + "\r\n")
                time.sleep(.1)
                (control / "stop").touch()
                self.wait_file(control / "finished", master, timeout=16)
                receipt = json.loads((control / "finished").read_text())
                self.assertEqual(receipt, dict(returncode=0, requested=True, forced=False, error=None))
                lines = [json.loads(line) for line in cast.read_text().splitlines() if line]
                self.assertEqual(lines[0]["term"]["cols"], 120)
                self.assertIn(marker, "".join(event[2] for event in lines[1:] if event[1] == "o"))
                (control / "release").touch()
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    done, status = os.waitpid(pid, os.WNOHANG)
                    if done:
                        reaped = True
                        self.assertEqual(os.waitstatus_to_exitcode(status), 0)
                        break
                    time.sleep(.05)
                self.assertTrue(reaped)
            finally:
                if not reaped:
                    os.kill(pid, signal.SIGKILL)
                    os.waitpid(pid, 0)
                os.close(master)

    def wait_file(self, path, master, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.exists():
                return
            if select.select([master], [], [], .05)[0]:
                data = os.read(master, 65536)
                # Respond to the recorder's terminal capability query.
                if b"\x1b[c" in data:
                    os.write(master, b"\x1b[?1;2c")
        self.fail(f"Timed out waiting for {path.name}")


class SupervisorFailure(unittest.TestCase):
    def test_missing_recorder_and_forced_shutdown_cannot_report_success(self):
        from kittydemo import recorder
        for mode in ("missing", "forced"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                control = Path(directory)
                (control / "start").touch()
                (control / "stop").touch()
                (control / "release").touch()
                process = Mock()
                process.poll.return_value = None
                process.wait.side_effect = [subprocess.TimeoutExpired("asciinema", 2), -9] if mode == "forced" else None
                with patch.object(recorder.signal, "signal"), patch.object(
                    recorder.subprocess, "Popen", side_effect=FileNotFoundError("asciinema missing") if mode == "missing" else None,
                    return_value=process
                ), patch.object(recorder.time, "monotonic", side_effect=iter(range(0, 100, 5))), patch.object(recorder.time, "sleep"):
                    self.assertEqual(recorder.supervise(control, control / "out.cast"), 1)
                receipt = json.loads((control / "finished").read_text())
                self.assertTrue(receipt["forced"])
                self.assertNotEqual(receipt["returncode"], 0)
                if mode == "forced":
                    process.kill.assert_called_once()
                    self.assertEqual(process.wait.call_count, 2)

    def test_controller_cleanup_does_not_mask_original_interruption(self):
        source = Path(__file__).resolve().parents[1] / "sample_command_file.sh"
        with patch.object(driver, "claim_session"), patch.object(driver, "claim_controller_window"), patch.object(
            cli, "run", side_effect=KeyboardInterrupt
        ), patch.object(driver, "release_controller_window", side_effect=OSError("title failed")), patch.object(
            driver, "release_session", side_effect=OSError("claim failed")
        ) as release, redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(cli.main([str(source)]), 130)
            release.assert_called_once()
            self.assertIn("title failed", stderr.getvalue())
            self.assertIn("claim failed", stderr.getvalue())
