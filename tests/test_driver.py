"""PTY selection without controlling any existing Kitty windows."""

import os
import pty
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from kittydemo import driver


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
        self.kitty.side_effect = lambda *args: self.devices.add(self.outer)
        self.stack.enter_context(patch.object(driver, "_windows", return_value=[{"title": driver.TITLE, "pid": 42}]))
        self.terminal_of = self.stack.enter_context(patch.object(driver, "_terminal_of", return_value=self.outer))

    def test_live_selects_window_pty(self):
        self.assertEqual(driver.launch(False, None).tty_path, self.outer)

    def test_record_snapshot_excludes_outer_pty(self):
        def start_recorder(text):
            if text.startswith("asciinema rec "):
                self.devices.add(self.inner)
        self.send_text.side_effect = start_recorder
        self.assertEqual(driver.launch(True, Path("/tmp/test.cast")).tty_path, self.inner)

    def test_record_does_not_fall_back_to_outer_pty(self):
        with self.assertRaisesRegex(RuntimeError, "found 0"):
            driver.launch(True, Path("/tmp/test.cast"))

    def test_missing_outer_pty_stops_before_recorder_start(self):
        self.terminal_of.return_value = None
        with self.assertRaisesRegex(RuntimeError, "outer presentation terminal"):
            driver.launch(True, Path("/tmp/test.cast"))
        self.send_text.assert_not_called()


if __name__ == "__main__":
    unittest.main()
