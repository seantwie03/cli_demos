"""Exercise real terminal signals, canonical input, echo, and resize handling."""

import errno
import fcntl
import os
import pty
import select
import signal
import struct
import sys
import termios
import time
import unittest

CHILD = """
import os, sys, termios
from kittydemo.driver import Requests
os.environ.pop('COLUMNS', None)
os.environ.pop('LINES', None)
saved = termios.tcgetattr(0)
status = 0
try:
    with Requests() as requests:
        flags = termios.tcgetattr(0)[3]
        print('MODE', bool(flags & termios.ICANON), bool(flags & termios.ISIG), bool(flags & termios.ECHO), flush=True)
        print('READY', flush=True)
        while True:
            print('EVENT:' + requests.wait(), flush=True)
except KeyboardInterrupt:
    print('INTERRUPTED', flush=True)
    status = 130
except EOFError:
    print('EOF', flush=True)
finally:
    print('RESTORED', saved == termios.tcgetattr(0), flush=True)
sys.exit(status)
"""


class TerminalInput(unittest.TestCase):
    def setUp(self):
        self.pid, self.master = pty.fork()
        if self.pid == 0:
            os.execv(sys.executable, [sys.executable, "-c", CHILD])
        self.output = b""
        self.addCleanup(self.cleanup)
        self.until(b"READY")
        self.assertIn(b"MODE True True False", self.output)

    def cleanup(self):
        try:
            pid, _ = os.waitpid(self.pid, os.WNOHANG)
            if pid == 0:
                os.kill(self.pid, signal.SIGKILL)
                os.waitpid(self.pid, 0)
        except ChildProcessError:
            pass
        os.close(self.master)

    def until(self, marker):
        deadline = time.monotonic() + 5
        while marker not in self.output:
            if time.monotonic() >= deadline:
                self.fail(f"Timed out waiting for {marker!r}: {self.output!r}")
            if select.select([self.master], [], [], 0.05)[0]:
                try:
                    chunk = os.read(self.master, 8192)
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                    self.fail(f"Child exited before {marker!r}: {self.output!r}")
                self.output += chunk

    def test_ctrl_c_interrupts_and_restores_terminal(self):
        os.write(self.master, b"\x03")
        self.until(b"RESTORED True")
        self.assertIn(b"INTERRUPTED", self.output)
        self.assertNotIn(b"EVENT:advance", self.output)
        _, status = os.waitpid(self.pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 130)

    def test_eof_exits_without_advancing(self):
        os.write(self.master, b"\x04")
        self.until(b"RESTORED True")
        self.assertIn(b"EOF", self.output)
        self.assertNotIn(b"EVENT:", self.output)

    def test_enter_carriage_return_advances_once(self):
        os.write(self.master, b"\r")
        self.until(b"EVENT:advance")
        os.write(self.master, b"\x04")
        self.until(b"RESTORED True")
        self.assertEqual(self.output.count(b"EVENT:advance"), 1)

    def test_mapping_requests_are_not_echoed_or_debounced(self):
        os.write(self.master, b"back\nforward\nscroll-up\nscroll-down\nunknown\n\n\n")
        self.until(b"EVENT:advance\r\nEVENT:advance")
        self.assertEqual(self.output.count(b"EVENT:"), 6)
        self.assertNotIn(b"unknown", self.output)
        self.assertNotIn(b"\r\nback\r\n", self.output)

    def test_resize_wakes_wait_without_losing_partial_request(self):
        os.write(self.master, b"ba")
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", 35, 105, 0, 0))
        self.until(b"EVENT:resize")
        self.assertNotIn(b"EVENT:advance", self.output)
        os.write(self.master, b"ck\n")
        self.until(b"EVENT:back")
