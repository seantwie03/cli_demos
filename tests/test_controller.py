import importlib.util
import io
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from kittydemo import driver, hud
from kittydemo.controller import Cursor
from kittydemo.engine import parse

spec = importlib.util.spec_from_file_location(
    "kitty_demo", Path(__file__).resolve().parents[1] / "kitty-demo.py"
)
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class Navigation(unittest.TestCase):
    def test_restart_then_previous_and_forward_skip_run(self):
        cursor = Cursor(parse("pwd\nls\n"))
        cursor.navigate("back")
        self.assertEqual(cursor.index, 0)
        cursor.navigate("forward")
        self.assertEqual(cursor.index, 2)
        cursor.advanced()
        self.assertEqual(cursor.index, 3)
        cursor.navigate("back")
        self.assertEqual(cursor.index, 2)
        cursor.navigate("back")
        self.assertEqual(cursor.index, 0)
        cursor.advanced()
        cursor.navigate("forward")
        self.assertEqual(cursor.index, 2)

    def test_headers_and_immediate_keys_are_stops(self):
        cursor = Cursor(parse("pwd\nclear\n#^ Section\n# detail\n#@ noenter\nq\n"))
        cursor.navigate("forward")
        self.assertEqual(cursor.steps[cursor.index].kind, "header")
        self.assertTrue(cursor.steps[cursor.index].clears)
        cursor.navigate("forward")
        self.assertEqual(cursor.steps[cursor.index].kind, "send")
        cursor.navigate("back")
        self.assertEqual(cursor.steps[cursor.index].kind, "header")

    def test_completion_and_empty_file_boundaries(self):
        for source in ("", "pwd\n"):
            with self.subTest(source=source):
                cursor = Cursor(parse(source))
                while not cursor.finished:
                    cursor.advanced()
                cursor.navigate("forward")
                self.assertTrue(cursor.finished)
                cursor.navigate("back")
                self.assertEqual(cursor.finished, not bool(source))
                self.assertEqual(cursor.index, 0)


class Playback(unittest.TestCase):
    def play(self, source, requests, record=False):
        steps = parse(source)
        frames = []
        render = hud.render

        def capture(cursor, **kwargs):
            frames.append((cursor.index, cursor.finished))
            return render(cursor, size=(80, 24), **kwargs)

        with patch.object(driver, "Requests") as reader, patch.object(
            driver, "perform"
        ) as perform, patch.object(cli.time, "sleep") as sleep, patch.object(
            cli.sys, "stdout", io.StringIO()
        ), patch.object(
            hud, "render", side_effect=capture
        ):
            reader.return_value.__enter__.return_value.wait.side_effect = requests
            cli.play(
                SimpleNamespace(record=record, pause=3),
                Path("demo.sh"),
                steps,
                object(),
            )
            return (
                [call.args[1] for call in perform.call_args_list],
                frames,
                sleep.call_args_list,
                reader.call_count,
            )

    def test_f2_only_matches_record_sequence_and_pauses(self):
        source = "clear\n#^ Section\n#! note\npwd\n#@ pause 7\nls\n#@ noenter\nq\n"
        steps = parse(source)
        live, _, _, _ = self.play(source, ["advance"] * (len(steps) + 1))
        recorded, _, sleeps, reader_count = self.play(source, [], record=True)
        self.assertEqual(live, steps)
        self.assertEqual(recorded, steps)
        self.assertEqual(reader_count, 0)
        self.assertEqual(
            [call.args[0] for call in sleeps],
            [s.pause if s.pause is not None else 3 for s in steps] + [3],
        )

    def test_detour_retypes_canceled_command(self):
        performed, _, _, _ = self.play(
            "pwd\n", ["advance", "back", "advance", "advance", "advance", "advance"]
        )
        self.assertEqual([s.kind for s in performed], ["arm", "arm", "run", "end"])

    def test_navigation_resize_and_scroll_never_perform(self):
        performed, _, _, _ = self.play(
            "pwd\nclear\n#^ Section\n",
            [
                "forward",
                "back",
                "scroll-down",
                "scroll-up",
                "resize",
                "forward",
                "forward",
                "advance",
                "advance",
            ],
        )
        self.assertEqual([s.kind for s in performed], ["end"])

    def test_revisit_after_completion(self):
        performed, frames, _, _ = self.play(
            "#@ noenter\nq\n",
            ["advance", "advance", "back", "advance", "advance", "advance"],
        )
        self.assertEqual([s.kind for s in performed], ["send", "end", "send", "end"])
        self.assertIn((0, False), frames[3:])

    def test_header_performs_clear_and_full_content_only_on_advance(self):
        steps = parse("clear\n#^ Title\n# detail\n")
        cursor = Cursor(steps)
        with patch.object(driver, "send_text") as text, patch.object(
            driver, "send_key"
        ) as key, patch.object(driver, "draw_header") as draw, patch.object(
            driver.time, "sleep"
        ):
            cursor.navigate("forward")
            cursor.navigate("back")
            draw.assert_not_called()
            driver.perform(object(), steps[cursor.index])
            text.assert_called_once_with("clear")
            key.assert_called_once_with("enter")
            self.assertEqual(draw.call_args.args[1], ("Title", "detail"))

    def test_interrupt_and_eof_release_claim_without_closing_live_window(self):
        source = Path(__file__).resolve().parents[1] / "sample_command_file.sh"
        for error, status in ((KeyboardInterrupt, 130), (EOFError, 1)):
            with self.subTest(error=error), patch.object(
                driver, "claim_session"
            ), patch.object(driver, "claim_controller_window"), patch.object(
                driver, "release_session"
            ) as release, patch.object(
                driver, "release_controller_window"
            ) as title, patch.object(
                driver, "launch"
            ), patch.object(
                driver, "teardown"
            ) as teardown, patch.object(
                cli, "play", side_effect=error
            ), patch.object(
                cli.sys, "stderr", io.StringIO()
            ):
                self.assertEqual(cli.main([str(source)]), status)
                release.assert_called_once()
                title.assert_called_once()
                teardown.assert_not_called()
