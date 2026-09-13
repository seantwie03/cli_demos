import re
import unittest

from kittydemo import hud
from kittydemo.controller import Cursor
from kittydemo.engine import parse


def lines(frame):
    rows = re.split(r"\x1b\[\d+;1H", frame.text)[1:]
    return [re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", row) for row in rows]


class Hud(unittest.TestCase):
    def render(self, cursor, size=(80, 24), scroll=0):
        return hud.render(cursor, name="demo.sh", size=size, scroll=scroll)

    def test_one_label_and_shared_type_enter_row(self):
        cursor = Cursor(parse("pwd\nls\n"))
        before = lines(self.render(cursor))
        cursor.advanced()
        after = lines(self.render(cursor))
        self.assertEqual(
            next(i for i, row in enumerate(before) if row.startswith("[TYPE]")),
            next(i for i, row in enumerate(after) if row.startswith("[ENTER]")),
        )
        self.assertEqual(sum("pwd" in row for row in before), 1)
        self.assertNotIn("→", "\n".join(before + after))
        self.assertIn("[ENTER]", "\n".join(after))
        cursor.navigate("back")
        self.assertEqual(lines(self.render(cursor)), before)
        cursor.advanced()
        cursor.advanced()
        output = "\n".join(lines(self.render(cursor)))
        self.assertRegex(output, r"\[TYPE\]\s+ls")
        self.assertEqual(
            len(re.findall(r"\[(?:TYPE|ENTER|SHOW|CLEAR\+SHOW|SEND|END)\]", output)), 1
        )

    def test_five_previous_and_next_without_run_rows(self):
        cursor = Cursor(parse("\n".join(f"command_{i:02}" for i in range(13))))
        cursor.index = 12
        rows = lines(self.render(cursor, (100, 40)))
        body = "\n".join(rows[2:-1])
        self.assertNotIn("command_00", body)
        self.assertNotIn("command_12", body)
        self.assertEqual(len(re.findall("command_", body)), 11)
        self.assertEqual(len(rows), 40)

    def test_header_prefix_truncation_and_clear_label(self):
        cursor = Cursor(
            parse("clear\n#^ " + "long title " * 20 + "\n# secret continuation\npwd\n")
        )
        rows = lines(self.render(cursor, (45, 20)))
        self.assertRegex("\n".join(rows), r"\[CLEAR\+SHOW\]\s+HEADER: .*…")
        self.assertNotIn("secret continuation", "\n".join(rows))
        self.assertTrue(all(hud.columns(row) <= 45 for row in rows))
        cursor.advanced()
        self.assertNotIn("[CLEAR+SHOW]", "\n".join(lines(self.render(cursor))))

    def test_notes_stay_with_command_across_phases_and_navigation(self):
        cursor = Cursor(parse("#! first note\npwd\n#! second note\nls\n"))
        before = lines(self.render(cursor))
        cursor.advanced()
        during = lines(self.render(cursor))
        self.assertEqual(
            [row for row in before if "NOTE:" in row],
            [row for row in during if "NOTE:" in row],
        )
        cursor.navigate("forward")
        cursor.navigate("back")
        self.assertEqual(lines(self.render(cursor)), before)

    def test_height_removes_previous_groups_first(self):
        cursor = Cursor(parse("\n".join(f"#! note_{i}\ncmd_{i}" for i in range(8))))
        cursor.index = 6
        rows = lines(self.render(cursor, (80, 11)))
        body = "\n".join(rows[2:-1])
        self.assertNotIn("cmd_2", body)
        self.assertIn("cmd_6", body)
        self.assertNotIn("cmd_7", body)
        for i in range(8):
            self.assertEqual(f"note_{i}" in body, f"cmd_{i}" in body)

    def test_oversized_note_is_fully_reachable_and_command_pinned(self):
        notes = [f"Note line {i:02}" for i in range(30)]
        cursor = Cursor(parse("\n".join("#! " + line for line in notes) + "\npwd\n"))
        seen = set()
        scroll = 0
        for _ in range(40):
            frame = self.render(cursor, (60, 10), scroll)
            output = "\n".join(lines(frame))
            self.assertRegex(output, r"\[TYPE\]\s+pwd")
            self.assertNotIn(
                "…", "\n".join(row for row in lines(frame) if "NOTE:" in row)
            )
            seen.update(re.findall(r"Note line \d+", output))
            scroll = frame.scroll + max(1, frame.page_size - 1)
        self.assertEqual(seen, set(notes))
        self.assertEqual(self.render(cursor, (60, 50), scroll).scroll, 0)

    def test_wrap_preserves_whitespace_and_unicode_content(self):
        for text in ("long words " * 20, "界面 a e\u0301 " * 20, " " * 30, "x" * 60):
            wrapped = hud._wrap(text, 17)
            self.assertEqual("".join(wrapped), text)
            self.assertTrue(all(hud.columns(row) <= 17 for row in wrapped))
        self.assertEqual(hud._wrap("first\n\nlast", 20), ["first", "", "last"])

    def test_small_windows_and_resize(self):
        cursor = Cursor(parse("#! " + "some note " * 20 + "\nclear\n#^ Title\n"))
        for width, height in ((20, 5), (40, 8), (80, 24), (120, 40)):
            rows = lines(self.render(cursor, (width, height)))
            self.assertEqual(len(rows), height)
            self.assertTrue(all(hud.columns(row) <= width for row in rows))
