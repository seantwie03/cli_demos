"""PTY selection without controlling any existing Kitty windows."""

import json
import os
import pty
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from kittydemo import driver
from kittydemo.engine import parse


class RemoteControl(unittest.TestCase):
    def test_text_payload_reaches_child_stdin_verbatim(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "kitty"
            executable.write_text(
                f"#!{sys.executable}\n"
                "import json, sys\n"
                "print(json.dumps([sys.argv[1:], sys.stdin.buffer.read().hex()]))\n"
            )
            executable.chmod(0o700)
            payloads = (
                r"printf '%s\n' hello",
                r"\t\r\x03\e\u21fa\\",
                "  café\ttext\r\n  ",
                "--help",
                "",
            )
            with patch.dict(os.environ, {"PATH": directory}):
                original = driver.kitty
                for payload in payloads:
                    with self.subTest(payload=payload), patch.object(
                        driver, "kitty", wraps=original
                    ) as invoke:
                        results = []
                        invoke.side_effect = lambda *args, **kwargs: results.append(original(*args, **kwargs))
                        driver.send_text(payload, match="id:7")
                        arguments, received = json.loads(results[0].stdout)
                        self.assertEqual(arguments, ["@", "send-text", "--match", "id:7", "--stdin"])
                        self.assertEqual(bytes.fromhex(received), payload.encode("utf-8"))

    def test_type_and_noenter_steps_use_literal_text_without_enter(self):
        payload = r"printf '%s\n' hello"
        for prefix in ("", "#@ noenter\n"):
            with self.subTest(prefix=prefix), patch.object(driver, "kitty") as invoke:
                driver.perform(driver.Session(window_id=7), parse(prefix + payload)[0])
                invoke.assert_called_once_with(
                    "send-text", "--match", "id:7", "--stdin", input=payload
                )

    def test_vim_logrotate_block_preserves_indentation_through_playback(self):
        source = (
            "vim /etc/logrotate.d/demo\n"
            "i/var/log/demo.log {\n"
            "    size 1k\n"
            "    rotate 2\n"
            "    compress\n"
            "    missingok\n"
            "#@ noenter\n}\n#@ key escape\n:wq\n"
        )
        with patch.object(driver.subprocess, "run") as run:
            for step in parse(source)[:-1]:
                driver.perform(driver.Session(window_id=7), step)
        delivered = []
        for call in run.call_args_list:
            args = call.args[0]
            if args[2] == "send-text":
                self.assertIn("--stdin", args)
                delivered.append(call.kwargs["input"])
            else:
                delivered.append({"enter": "\r", "escape": "\x1b"}[args[-1]])
        self.assertEqual("".join(delivered),
                         "vim /etc/logrotate.d/demo\r"
                         "i/var/log/demo.log {\r"
                         "    size 1k\r    rotate 2\r    compress\r    missingok\r"
                         "}\x1b:wq\r")

    def test_send_commands_inherit_endpoint_without_transport_override(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "kitty"
            executable.write_text('#!/bin/sh\nprintf "%s\\n" "${KITTY_LISTEN_ON-unset}" "$@"\n')
            executable.chmod(0o700)
            for endpoint in (None, "unix:/run/user/1000/kitty-demo-12345"):
                with self.subTest(endpoint=endpoint), patch.dict(os.environ, {"PATH": directory}):
                    os.environ.pop("KITTY_LISTEN_ON", None)
                    if endpoint:
                        os.environ["KITTY_LISTEN_ON"] = endpoint
                    original = driver.kitty
                    with patch.object(driver, "kitty") as invoke:
                        # Capture the actual child's response through the real wrapper.
                        results = []
                        invoke.side_effect = lambda *args, **kwargs: results.append(original(*args, **kwargs))
                        driver.send_key("enter")
                        driver.send_text("hello")
                    for result, command in zip(results, ("send-key", "send-text")):
                        self.assertEqual(result.stdout.splitlines()[:3],
                                         [endpoint or "unset", "@", command])

    def test_valid_listings(self):
        for payload, expected in (("[]", []), ('[{"tabs": [{"windows": [{"id": 7}]}]}]', [{"id": 7}])):
            with self.subTest(payload=payload), patch.object(driver, "kitty", return_value=subprocess.CompletedProcess([], 0, payload)):
                self.assertEqual(driver._windows(), expected)

    def test_failed_or_invalid_listing_never_looks_empty(self):
        errors = [FileNotFoundError("kitty missing"),
                  subprocess.CalledProcessError(1, ["kitty"], stderr="Permission denied"),
                  subprocess.CalledProcessError(1, ["kitty"], stderr="Connection refused"),
                  subprocess.TimeoutExpired(["kitty"], 5)]
        for error in errors:
            with self.subTest(error=error), patch.dict(os.environ, {"KITTY_LISTEN_ON": "unix:/missing"}), patch.object(driver, "kitty", side_effect=error) as invoke:
                with self.assertRaisesRegex(driver.KittyConnectionError, "unix:/missing"):
                    driver._windows()
                invoke.assert_called_once_with("ls")
        for payload in ("", "bad json", "null", "{}", "[{}]", '[{"tabs": [null]}]', '[{"tabs": [{"windows": [1]}]}]'):
            with self.subTest(payload=payload), patch.object(driver, "kitty", return_value=subprocess.CompletedProcess([], 0, payload)):
                with self.assertRaisesRegex(driver.KittyConnectionError, "Invalid window listing"):
                    driver._windows()


class TtyDiscovery(unittest.TestCase):
    def test_snapshot_excludes_non_numeric_entries(self):
        with patch.object(Path, "iterdir", return_value=iter([
            Path("/dev/pts/ptmx"), Path("/dev/pts/9"), Path("/dev/pts/10")
        ])):
            self.assertEqual(driver.tty_paths(), {Path("/dev/pts/9"), Path("/dev/pts/10")})

    def test_selects_new_real_pty(self):
        before = driver.tty_paths()
        master, slave = pty.openpty()
        try:
            self.assertEqual(driver.new_tty(before), Path(os.ttyname(slave)))
        finally:
            os.close(master)
            os.close(slave)

    def test_refuses_missing_or_ambiguous_new_devices(self):
        before = {Path("/dev/pts/1")}
        for extra in (set(), {Path("/dev/pts/9"), Path("/dev/pts/10")}):
            with self.subTest(extra=extra), patch.object(driver, "tty_paths", return_value=before | extra):
                with self.assertRaisesRegex(RuntimeError, f"found {len(extra)}"):
                    driver.new_tty(before)


class LaunchDiscovery(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": ""}))
        self.stack.enter_context(patch.object(driver.time, "sleep"))
        self.kitty = self.stack.enter_context(patch.object(driver, "kitty"))
        self.send_text = self.stack.enter_context(patch.object(driver, "send_text"))
        self.stack.enter_context(patch.object(driver, "send_key"))
        self.outer = Path("/dev/pts/9")
        self.inner = Path("/dev/pts/10")
        self.devices = {Path("/dev/pts/1")}
        self.stack.enter_context(patch.object(driver, "tty_paths", side_effect=lambda: self.devices.copy()))
        def launch(*args, **kwargs):
            if args[0] == "launch":
                self.devices.add(self.outer)
            return subprocess.CompletedProcess([], 0, "7")
        self.kitty.side_effect = launch
        self.abort = self.stack.enter_context(patch.object(driver.Session, "abort", autospec=True, side_effect=lambda session: session.dispose()))
        self.wait_file = self.stack.enter_context(patch.object(driver.Session, "wait_file", autospec=True))
        self.stack.enter_context(patch.object(driver.time, "monotonic", side_effect=iter(range(100))))
        self.stack.enter_context(patch.object(driver, "_windows", return_value=[{"title": driver.TITLE, "pid": 42, "id": 7}]))
        self.terminal_of = self.stack.enter_context(patch.object(driver, "_terminal_of", return_value=self.outer))

    def test_live_selects_window_pty(self):
        self.assertEqual(driver.launch(False, None).tty_path, self.outer)

    def test_record_snapshot_excludes_outer_pty(self):
        def start_recorder(session, name, *args):
            if name == "running":
                self.assertTrue((session.control / "start").exists())
                self.devices.add(self.inner)
        self.wait_file.side_effect = start_recorder
        session = driver.launch(True, Path("/tmp/test.cast"))
        self.addCleanup(session.dispose)
        self.assertEqual(session.tty_path, self.inner)
        self.assertEqual(session.window_id, 7)
        self.send_text.assert_called_once_with("PS1='$ '; unset PROMPT_COMMAND PS0; clear", match="id:7")

    def test_record_does_not_fall_back_to_outer_pty(self):
        with self.assertRaisesRegex(RuntimeError, "found 0"):
            driver.launch(True, Path("/tmp/test.cast"))
        self.abort.assert_called_once()
        self.assertEqual(self.abort.call_args.args[0].window_id, 7)
        self.send_text.assert_not_called()

    def test_missing_outer_pty_stops_before_recorder_start(self):
        self.terminal_of.return_value = None
        with self.assertRaisesRegex(RuntimeError, "outer presentation terminal"):
            driver.launch(True, Path("/tmp/test.cast"))
        self.send_text.assert_not_called()


if __name__ == "__main__":
    unittest.main()
