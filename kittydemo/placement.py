"""Bounded, optional compositor placement; never changes permanent settings."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time


TIMEOUT = 8.0


def warn(error) -> None:
    print(f"warning: presentation placement: {error}", file=sys.stderr)


def run(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=3).stdout


def other_output(names, source):
    names = sorted(set(names))
    if not names:
        raise RuntimeError("no active outputs")
    return names[(names.index(source) + 1) % len(names)] if source in names else names[0]


def dbus(method, *args, path="/Scripting"):
    return run("gdbus", "call", "--session", "--dest", "org.kde.KWin",
               "--object-path", path, "--method", method, *args)


class KDE:
    def __init__(self, app_id):
        self.app_id = app_id
        self.directory = tempfile.TemporaryDirectory(prefix="kitty-demo-kwin-")
        self.names = []

    def load(self, name, source):
        path = Path(self.directory.name) / (name + ".js")
        path.write_text(source)
        # Register ownership before calling: a lost reply may still load the script.
        self.names.append(name)
        response = dbus("org.kde.kwin.Scripting.loadScript", str(path), name)
        match = re.fullmatch(r"\((-?\d+),\)\s*", response)
        if not match or int(match[1]) < 0:
            raise RuntimeError(f"KWin could not load placement script: {response.strip()}")
        return int(match[1])

    def wait_removed(self, name):
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline:
            result = dbus("org.kde.kwin.Scripting.isScriptLoaded", name).strip()
            if result == "(false,)":
                return
            if result != "(true,)":
                raise RuntimeError(f"unexpected KWin acknowledgement: {result}")
            time.sleep(.1)
        raise RuntimeError("KWin placement acknowledgement timed out")

    def prepare(self):
        self.ready = self.app_id + "-ready"
        self.done = self.app_id + "-done"
        # Unstarted marker scripts provide acknowledgements without a D-Bus server
        # dependency. Only explicit success in our main script removes each marker.
        self.load(self.ready, "// readiness marker\n")
        self.load(self.done, "// completion marker\n")
        source = (Path(__file__).with_name("placement.js")).read_text()
        source = "const config = " + json.dumps(dict(appId=self.app_id, ready=self.ready, done=self.done)) + ";\n" + source
        number = self.load(self.app_id, source)
        dbus("org.kde.kwin.Script.run", path=f"/Scripting/Script{number}")
        self.wait_removed(self.ready)

    def finish(self):
        self.wait_removed(self.done)

    def close(self):
        try:
            for name in reversed(self.names):
                try:
                    dbus("org.kde.kwin.Scripting.unloadScript", name)
                except Exception as error:
                    warn(f"could not unload {name}: {error}")
        finally:
            self.directory.cleanup()


class Niri:
    def __init__(self, app_id):
        self.app_id = app_id

    def prepare(self):
        workspaces = json.loads(run("niri", "msg", "--json", "workspaces"))
        self.source = next((w["output"] for w in workspaces if w["is_focused"]), None)

    def finish(self):
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline:
            windows = json.loads(run("niri", "msg", "--json", "windows"))
            matches = [w for w in windows if w.get("app_id") == self.app_id]
            if len(matches) > 1:
                raise RuntimeError("ambiguous Niri presentation window")
            if matches:
                outputs = json.loads(run("niri", "msg", "--json", "outputs"))
                target = other_output([name for name, info in outputs.items()
                                       if info.get("current_mode") is not None], self.source)
                helper = Path(__file__).resolve().parent.parent / "niri-maximize_on_other_monitor.sh"
                run(str(helper), str(matches[0]["id"]), target)
                return
            time.sleep(.1)
        raise RuntimeError("Niri presentation window did not appear")

    def close(self):
        pass


class Placement:
    def __init__(self, app_id):
        desktops = set(os.environ.get("XDG_CURRENT_DESKTOP", "").lower().split(":"))
        self.backend = KDE(app_id) if "kde" in desktops else Niri(app_id) if "niri" in desktops else None

    def __enter__(self):
        if self.backend:
            try:
                self.backend.prepare()
            except Exception as error:
                warn(error)
                self.backend.close()
                self.backend = None
            except BaseException:
                self.backend.close()
                raise
        return self

    def finish(self):
        if self.backend:
            try:
                self.backend.finish()
            except Exception as error:
                warn(error)

    def __exit__(self, *_):
        if self.backend:
            self.backend.close()
