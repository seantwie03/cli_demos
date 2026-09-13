import unittest
from unittest.mock import patch

from kittydemo import driver, hud
from kittydemo.controller import Cursor
from kittydemo.engine import CommandFileError, parse


class KeySteps(unittest.TestCase):
    def test_arguments_are_preserved_and_validation_is_left_to_kitty(self):
        for argument in ('Ctrl+x', 'ctrl+shift+f1', '--help', 'unknown  key'):
            with self.subTest(argument=argument):
                steps = parse(f'  #@ key {argument}  \n')
                self.assertEqual([(s.kind, s.text) for s in steps[:-1]], [('key', argument)])
                self.assertEqual(steps[0].line, 1)

    def test_empty_argument_and_pending_noenter_are_errors(self):
        for source, message in (
            ('pwd\n#@ key  \n', 'line 2: key needs'),
            ('#@ noenter\n#@ pause 2\n#@ key ctrl+x\n', 'line 1:.*not a key step'),
        ):
            with self.subTest(source=source):
                with self.assertRaisesRegex(CommandFileError, message):
                    parse(source)

    def test_notes_pause_and_consecutive_final_keys(self):
        steps = parse('#! save\n#@ pause 2\n#@ key ctrl+x\n#@ key enter\n')
        self.assertEqual([s.kind for s in steps], ['key', 'key', 'end'])
        self.assertEqual(steps[0].notes, ('save',))
        self.assertEqual(steps[0].pause, 2)
        self.assertEqual(steps[1].notes, ())
        self.assertIsNone(steps[1].pause)

    def test_key_prevents_clear_header_merge(self):
        steps = parse('clear\n#! save\n#@ pause 2\n#@ key ctrl+x\n#^ Title\n')
        self.assertEqual([s.kind for s in steps], ['arm', 'run', 'key', 'header', 'end'])
        self.assertFalse(steps[3].clears)
        self.assertEqual(steps[2].notes, ('save',))
        self.assertEqual(steps[2].pause, 2)

    def test_nano_sequence_has_no_extra_enter_after_ctrl_x(self):
        steps = parse('nano demo.txt\nA note for this demonstration.\n#@ key ctrl+x\ny\n')
        with patch.object(driver.subprocess, 'run') as run:
            for step in steps[:-1]:
                driver.perform(object(), step)
        self.assertEqual(
            [c.args[0][2:] for c in run.call_args_list],
            [[command, '--match', driver.MATCH, '--', value] for command, value in (
                ('send-text', 'nano demo.txt'), ('send-key', 'enter'),
                ('send-text', 'A note for this demonstration.'), ('send-key', 'enter'),
                ('send-key', 'ctrl+x'), ('send-text', 'y'), ('send-key', 'enter'),
            )],
        )

    def test_key_argument_is_one_subprocess_argument(self):
        with patch.object(driver.subprocess, 'run') as run:
            driver.perform(object(), parse('#@ key --help\n')[0])
        run.assert_called_once_with(
            ['kitty', '@', 'send-key', '--match', driver.MATCH, '--', '--help'],
            check=True, capture_output=True, text=True,
        )

    def test_navigation_and_hud_do_not_deliver_keys(self):
        cursor = Cursor(parse('pwd\n#! save now\n#@ key Ctrl+x\ny\n'))
        with patch.object(driver.subprocess, 'run') as run:
            cursor.navigate('forward')
            frame = hud.render(cursor, name='demo.sh', size=(80, 24)).text
            self.assertIn('[KEY]', frame)
            self.assertIn('Ctrl+x', frame)
            self.assertIn('NOTE: save now', frame)
            cursor.navigate('forward')
            self.assertNotIn('[KEY]', hud.render(cursor, name='demo.sh').text)
            cursor.navigate('back')
            self.assertEqual(cursor.steps[cursor.index].kind, 'key')
            run.assert_not_called()
            driver.perform(object(), cursor.steps[cursor.index])
            run.assert_called_once()
