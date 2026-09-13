import io
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

from kittydemo import placement


class PlacementContracts(unittest.TestCase):
    def test_output_order_and_missing_source(self):
        self.assertEqual(placement.other_output(["eDP-1"], "eDP-1"), "eDP-1")
        self.assertEqual(placement.other_output(["eDP-1", "HDMI-1"], "eDP-1"), "HDMI-1")
        self.assertEqual(placement.other_output(["C", "A", "B"], "A"), "B")
        self.assertEqual(placement.other_output(["B", "A"], "removed"), "A")
        with self.assertRaises(RuntimeError):
            placement.other_output([], "A")

    def test_detection_and_warning_fallback_clean_up(self):
        for desktop, selected in (("KDE", "KDE"), ("plasma:KDE", "KDE"), ("niri", "Niri")):
            with self.subTest(desktop=desktop), patch.dict(placement.os.environ, {"XDG_CURRENT_DESKTOP": desktop}), patch.object(placement, selected) as backend, patch.object(placement.sys, "stderr", io.StringIO()) as stderr:
                backend.return_value.prepare.side_effect = FileNotFoundError("missing helper")
                with placement.Placement("owned") as operation:
                    operation.finish()
                backend.return_value.close.assert_called_once()
                backend.return_value.finish.assert_not_called()
                self.assertIn("missing helper", stderr.getvalue())
        with patch.dict(placement.os.environ, {"XDG_CURRENT_DESKTOP": "GNOME"}):
            with placement.Placement("owned") as operation:
                self.assertIsNone(operation.backend)

    def test_interrupt_unloads_prepared_backend(self):
        with patch.dict(placement.os.environ, {"XDG_CURRENT_DESKTOP": "KDE"}), patch.object(placement, "KDE") as backend:
            with self.assertRaises(KeyboardInterrupt):
                with placement.Placement("owned"):
                    raise KeyboardInterrupt
            backend.return_value.close.assert_called_once()

    def test_script_acknowledgements_and_cleanup(self):
        loaded = set()
        calls = []

        def bus(method, *args, **kwargs):
            calls.append((method, args, kwargs))
            if method.endswith("loadScript") and not method.endswith("unloadScript"):
                loaded.add(args[1])
                return "(4,)\n"
            if method.endswith(".run"):
                loaded.remove("owned-ready")
            if method.endswith("isScriptLoaded"):
                return "(true,)" if args[0] in loaded else "(false,)"
            if method.endswith("unloadScript"):
                loaded.discard(args[0])
            return "()"

        with patch.object(placement, "dbus", side_effect=bus):
            kde = placement.KDE("owned")
            try:
                kde.prepare()
                loaded.remove("owned-done")
                kde.finish()
            finally:
                kde.close()
        self.assertFalse(loaded)
        self.assertFalse(Path(kde.directory.name).exists())
        self.assertIn(("org.kde.kwin.Script.run", (), {"path": "/Scripting/Script4"}), calls)
        self.assertFalse(any(method.endswith(".start") for method, _, _ in calls))

    def test_load_failure_and_timeout_still_unload_owned_names(self):
        with patch.object(placement, "dbus", return_value="(-1,)") as bus:
            kde = placement.KDE("owned")
            try:
                with self.assertRaises(RuntimeError):
                    kde.prepare()
            finally:
                kde.close()
            bus.assert_any_call("org.kde.kwin.Scripting.unloadScript", "owned-ready")
        with patch.object(placement, "dbus", return_value="(true,)"), patch.object(placement.time, "monotonic", side_effect=[0, 0, 9]), patch.object(placement.time, "sleep"):
            kde = placement.KDE("owned")
            try:
                with self.assertRaisesRegex(RuntimeError, "timed out"):
                    kde.wait_removed("owned-ready")
            finally:
                kde.close()

    def test_niri_targets_unique_app_id_using_prelaunch_source(self):
        replies = [json.dumps([dict(is_focused=True, output="eDP-1")]),
                   json.dumps([dict(id=7, app_id="owned"), dict(id=9, app_id="other")]),
                   json.dumps({"HDMI-1": {"current_mode": 0}, "eDP-1": {"current_mode": 0}}), ""]
        with patch.object(placement, "run", side_effect=replies) as run:
            niri = placement.Niri("owned")
            niri.prepare()
            niri.finish()
            self.assertEqual(run.call_args.args[1:], ("7", "HDMI-1"))


@unittest.skipUnless(shutil.which("node"), "Node required to exercise compositor JS with fake outputs")
class ScriptBehavior(unittest.TestCase):
    def test_one_two_many_outputs_focus_hotplug_and_expiry(self):
        source = Path(placement.__file__).with_name("placement.js").read_text()
        for outputs, origin, later, expected in [(["eDP"], "eDP", None, "eDP"),
                                               (["eDP", "HDMI"], "eDP", None, "HDMI"),
                                               (["C", "A", "B"], "A", None, "B"),
                                               (["A", "B"], "A", ["C"], "C")]:
            harness = r'''
const assert = require('assert');
function signal() { const callbacks = new Set(); return {
 connect: f => callbacks.add(f), disconnect: f => callbacks.delete(f),
 emit: (...args) => Array.from(callbacks).forEach(f => f(...args)) }; }
const timers = [];
class QTimer { constructor() { this.timeout = signal(); this.active = false; timers.push(this); }
 start() { this.active = true; } stop() { this.active = false; } }
const acknowledgements = [];
function callDBus(...args) { acknowledgements.push(args[4]); }
const config = {appId:'owned',ready:'ready',done:'done'};
const workspace = {screens: INPUT.map(name => ({name})), activeWindow: {output:{name:ORIGIN}},
 windowAdded: signal(), windowRemoved: signal(),
 sendClientToScreen: (window, output) => { window.output = output; } };
'''.replace("INPUT", json.dumps(outputs)).replace("ORIGIN", json.dumps(origin))
            checks = '''
assert.deepEqual(acknowledgements, ['ready']);
workspace.activeWindow = {output:{name:'changed-focus'}};
if (LATER) workspace.screens = LATER.map(name => ({name}));
const other = {resourceClass:'unrelated'};
workspace.windowAdded.emit(other);
assert.equal(other.output, undefined);
const window = {resourceClass:'owned', maximizeMode:0,
 setMaximize: function(v,h) {assert(v && h);this.maximizeMode=3;}};
workspace.windowAdded.emit(window);
assert.equal(window.output.name, EXPECTED);
timers.filter(t => t.active && t.interval === 50).forEach(t => t.timeout.emit());
assert.deepEqual(acknowledgements, ['ready','done']);
const second = {resourceClass:'owned'};
workspace.windowAdded.emit(second);
assert.equal(second.output, undefined);
'''.replace("LATER", json.dumps(later)).replace("EXPECTED", json.dumps(expected))
            with self.subTest(outputs=outputs):
                subprocess.run(["node", "-e", harness + source + checks], check=True, capture_output=True, text=True)
            expired = '''
timers.filter(t => t.interval === 8000).forEach(t => t.timeout.emit());
const window = {resourceClass:'owned'};
workspace.windowAdded.emit(window);
assert.equal(window.output, undefined);
assert.deepEqual(acknowledgements, ['ready']);
'''
            subprocess.run(["node", "-e", harness + source + expired], check=True, capture_output=True, text=True)
