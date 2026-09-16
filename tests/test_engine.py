"""Rules the engine must keep, expressed as the press sequence they produce.

These are the decisions that were argued over rather than discovered, so they
are the ones worth pinning: notes never cost a press, a section transition
costs one press instead of three, and a header never advances on its own into
whatever follows it.
"""

import unittest

from kittydemo.engine import SENTINEL, CommandFileError, Step, parse


def sequence(source):
    """Reduce steps to (kind, label) pairs, which is what a press sequence is."""
    return [(step.kind, step.label) for step in parse(source)]


class CommandSteps(unittest.TestCase):
    def test_a_command_arms_then_runs(self):
        self.assertEqual(
            sequence("ls -l\n"),
            [("arm", "ls -l"), ("run", "ls -l"), ("end", SENTINEL)],
        )

    def test_every_file_ends_with_a_terminal_step(self):
        self.assertEqual(parse("")[-1].kind, "end")
        self.assertEqual(parse("ls\n")[-1].kind, "end")

    def test_command_whitespace_is_preserved_in_both_phases(self):
        for text in ("    size 1k", "\trotate 2", "    # config comment", "  text  "):
            with self.subTest(text=text):
                self.assertEqual(
                    sequence(text + "\n")[:2], [("arm", text), ("run", text)]
                )

    def test_indented_noenter_directive_preserves_command_whitespace(self):
        self.assertEqual(
            sequence("  #@ noenter\n    }\n"),
            [("send", "    }"), ("end", SENTINEL)],
        )


class Notes(unittest.TestCase):
    def test_a_note_never_costs_a_press(self):
        self.assertEqual(
            sequence("#! watch the exit status\nls -l\n"),
            [("arm", "ls -l"), ("run", "ls -l"), ("end", SENTINEL)],
        )

    def test_a_note_attaches_to_the_step_that_follows_it(self):
        steps = parse("#! watch the exit status\nls -l\n")
        self.assertEqual(steps[0].notes, ("watch the exit status",))
        self.assertEqual(steps[1].notes, ())

    def test_consecutive_notes_arrive_together(self):
        steps = parse("#! first\n#! second\nls\n")
        self.assertEqual(steps[0].notes, ("first", "second"))

    def test_a_note_before_a_header_attaches_to_the_header(self):
        steps = parse("#! notice the prompt\n#^ Next section\n")
        self.assertEqual(steps[0].kind, "header")
        self.assertEqual(steps[0].notes, ("notice the prompt",))

    def test_a_trailing_note_is_not_lost(self):
        steps = parse("ls\n#! nothing left to run\n")
        self.assertEqual(steps[-1].kind, "end")
        self.assertEqual(steps[-1].notes, ("nothing left to run",))


class Headers(unittest.TestCase):
    def test_a_header_block_is_one_press(self):
        steps = parse("#^ 1. Install httpd\n#   requires root\n#   takes a minute\n")
        self.assertEqual(steps[0].kind, "header")
        self.assertEqual(
            steps[0].lines,
            ("1. Install httpd", "  requires root", "  takes a minute"),
        )
        self.assertEqual(len(steps), 2)

    def test_a_header_does_not_advance_into_the_command_after_it(self):
        # The intro task list has to stay on screen while it is discussed.
        self.assertEqual(
            sequence("#^ Exercise: Backups\nsudo -i\n"),
            [
                ("header", "Exercise: Backups"),
                ("arm", "sudo -i"),
                ("run", "sudo -i"),
                ("end", SENTINEL),
            ],
        )

    def test_a_header_does_not_swallow_a_following_clear(self):
        steps = parse("#^ Exercise: Backups\n#   tasks\nclear\n")
        self.assertEqual([step.kind for step in steps[:3]], ["header", "arm", "run"])
        self.assertFalse(steps[0].clears)


class HeaderIndentation(unittest.TestCase):
    """The hierarchy inside a header block is carried by its indentation.

    `kitty-demo.sh` removes only the sigil and one space, so a source line
    indented under `Requirements` stays indented on screen. The Python engine
    has to agree exactly, or a recording made by one looks different from a
    recording made by the other.
    """

    SOURCE = """#^ Exercise: Backups
# Requirements
#   Host: servera
# Tasks
#   1. Write the script
"""

    def test_source_indentation_survives(self):
        self.assertEqual(
            parse(self.SOURCE)[0].lines,
            (
                "Exercise: Backups",
                "Requirements",
                "  Host: servera",
                "Tasks",
                "  1. Write the script",
            ),
        )

    def test_only_one_space_is_removed_after_the_sigil(self):
        self.assertEqual(parse("#^ T\n#    deep\n")[0].lines[1], "   deep")

    def test_leading_whitespace_before_the_sigil_is_ignored(self):
        self.assertEqual(parse("#^ T\n    #   x\n")[0].lines[1], "  x")

    def test_the_label_is_still_reported_without_padding(self):
        self.assertEqual(parse(self.SOURCE)[0].label, "Exercise: Backups")


class ClearHeaderMerge(unittest.TestCase):
    def test_clear_then_header_is_one_press(self):
        self.assertEqual(
            sequence("clear\n#^ 2. Schedule it\n"),
            [("header", "2. Schedule it"), ("end", SENTINEL)],
        )

    def test_the_merged_step_still_clears(self):
        self.assertTrue(parse("clear\n#^ 2. Schedule it\n")[0].clears)

    def test_the_merge_carries_the_header_continuation_lines(self):
        steps = parse("clear\n#^ 2. Schedule it\n#   in /etc/cron.d\n")
        self.assertEqual(steps[0].lines, ("2. Schedule it", "  in /etc/cron.d"))

    def test_clear_before_a_command_is_an_ordinary_command(self):
        self.assertEqual(
            sequence("clear\nls\n"),
            [
                ("arm", "clear"),
                ("run", "clear"),
                ("arm", "ls"),
                ("run", "ls"),
                ("end", SENTINEL),
            ],
        )

    def test_only_a_bare_clear_merges(self):
        self.assertEqual(parse("clear && ls\n#^ Next\n")[0].kind, "arm")

    def test_a_directive_between_the_clear_and_the_header_keeps_the_merge(self):
        # Writing the hold directly above the header is the natural place for
        # it, and must not cost the two presses that an unmerged clear does.
        steps = parse("clear\n#@ pause 70\n#^ Next\n")
        self.assertEqual([step.kind for step in steps], ["header", "end"])
        self.assertTrue(steps[0].clears)
        self.assertEqual(steps[0].pause, 70.0)

    def test_a_note_between_the_clear_and_the_header_keeps_the_merge(self):
        steps = parse("clear\n#! aside\n#^ Next\n")
        self.assertEqual([step.kind for step in steps], ["header", "end"])
        self.assertTrue(steps[0].clears)
        self.assertEqual(steps[0].notes, ("aside",))

    def test_a_clear_before_a_directive_and_a_command_does_not_merge(self):
        steps = parse("clear\n#@ pause 5\nls\n")
        self.assertEqual([step.kind for step in steps[:4]], ["arm", "run", "arm", "run"])

    def test_a_note_before_the_merge_rides_with_it(self):
        steps = parse("#! wipe the screen\nclear\n#^ Next\n")
        self.assertEqual(steps[0].kind, "header")
        self.assertEqual(steps[0].notes, ("wipe the screen",))


class Directives(unittest.TestCase):
    def test_pause_attaches_to_the_run_of_the_following_command(self):
        steps = parse("#@ pause 8\ndnf install -y httpd\n")
        self.assertIsNone(steps[0].pause)
        self.assertEqual(steps[1].kind, "run")
        self.assertEqual(steps[1].pause, 8.0)

    def test_pause_applies_to_a_header(self):
        self.assertEqual(parse("#@ pause 12\n#^ Exercise: Backups\n")[0].pause, 12.0)

    def test_noenter_makes_a_line_a_single_press(self):
        self.assertEqual(
            sequence("#@ noenter\nq\n"),
            [("send", "q"), ("end", SENTINEL)],
        )

    def test_noenter_applies_only_to_the_next_line(self):
        self.assertEqual(
            sequence("#@ noenter\nq\nls\n"),
            [
                ("send", "q"),
                ("arm", "ls"),
                ("run", "ls"),
                ("end", SENTINEL),
            ],
        )

    def test_a_directive_is_never_typed(self):
        self.assertNotIn("pause", [step.text for step in parse("#@ pause 3\nls\n")])

    def test_an_unknown_directive_is_refused(self):
        # A typo would otherwise be typed into the presentation window.
        with self.assertRaises(CommandFileError):
            parse("#@ pasue 8\nls\n")

    def test_pause_needs_a_number(self):
        with self.assertRaises(CommandFileError):
            parse("#@ pause soon\nls\n")


class Comments(unittest.TestCase):
    """A `#` line is header text inside a header block and typed anywhere else.

    Both readings are wanted. Inside a block it labels the section for the
    audience. Outside one it is a line to type: a shell comment the audience
    should read, or a comment line going into a config file under an editor.
    """

    def test_a_hash_comment_outside_a_header_is_typed_verbatim(self):
        self.assertEqual(
            sequence("ls\n# now check the service\n")[2:4],
            [
                ("arm", "# now check the service"),
                ("run", "# now check the service"),
            ],
        )

    def test_a_typed_comment_keeps_its_hash(self):
        """The `#` is what makes it a comment, so it must reach the shell."""
        step = parse("# Managed by Ansible\n")[0]
        self.assertTrue(step.text.startswith("#"))

    def test_a_typed_comment_gets_an_enter(self):
        """It has to be submitted, at a prompt and in an editor buffer alike."""
        self.assertEqual(
            [step.kind for step in parse("# a comment\n")],
            ["arm", "run", "end"],
        )

    def test_a_hash_comment_inside_a_header_is_a_continuation(self):
        self.assertEqual(
            parse("#^ Title\n#   detail\n")[0].lines, ("Title", "  detail")
        )

    def test_a_section_owns_every_comment_that_follows_it(self):
        """Spacing does not matter. Only a command closes a section header."""
        self.assertEqual(
            parse("#^ Title\n#   one\n\n#   two\n")[0].lines,
            ("Title", "  one", "  two"),
        )

    def test_a_command_is_what_makes_a_comment_typeable_again(self):
        steps = parse("#^ Title\n#   detail\nls\n# now read this\n")
        self.assertEqual(steps[0].lines, ("Title", "  detail"))
        self.assertEqual(
            [(step.kind, step.text) for step in steps[3:5]],
            [("arm", "# now read this"), ("run", "# now read this")],
        )

    def test_blank_lines_are_invisible_to_the_clear_header_merge(self):
        """The corpus writes `clear`, a blank line, then the header, 211 times.

        Each is a one-press section transition. A parser that read blank lines
        as structure would silently make every one of them cost three.
        """
        self.assertEqual(
            sequence("ls\nclear\n\n#^ Next\n"),
            [
                ("arm", "ls"),
                ("run", "ls"),
                ("header", "Next"),
                ("end", SENTINEL),
            ],
        )
        self.assertTrue(parse("ls\nclear\n\n#^ Next\n")[2].clears)

    def test_a_comment_is_typed_inside_an_editor_too(self):
        """A config file line that begins with `#`, entered under vim."""
        self.assertEqual(
            sequence("vim /etc/hosts\n#@ noenter\ni\n# Managed by hand\n")[-2:],
            [("run", "# Managed by hand"), ("end", SENTINEL)],
        )


class RealisticFile(unittest.TestCase):
    SOURCE = """kitten @ set-font-size 30.0 && ssh servera
clear

#^ Exercise: Backing Up /etc Nightly
#   Hosts: servera
#   Tasks
#     1. Write the script
clear

#^ 1. Write the script
sudo -i
#! run it by hand before trusting it to a schedule
/usr/local/bin/etc_backup.sh
clear

#^ 2. Clean up
rm -f /tmp/etc_*.tar.gz
"""

    def test_press_sequence(self):
        self.assertEqual(
            sequence(self.SOURCE),
            [
                ("arm", "kitten @ set-font-size 30.0 && ssh servera"),
                ("run", "kitten @ set-font-size 30.0 && ssh servera"),
                ("header", "Exercise: Backing Up /etc Nightly"),
                ("header", "1. Write the script"),
                ("arm", "sudo -i"),
                ("run", "sudo -i"),
                ("arm", "/usr/local/bin/etc_backup.sh"),
                ("run", "/usr/local/bin/etc_backup.sh"),
                ("header", "2. Clean up"),
                ("arm", "rm -f /tmp/etc_*.tar.gz"),
                ("run", "rm -f /tmp/etc_*.tar.gz"),
                ("end", SENTINEL),
            ],
        )

    def test_every_section_transition_merged_its_clear(self):
        # Including the one after the SSH, which wipes the login banner and
        # draws the intro header in a single press.
        headers = [step for step in parse(self.SOURCE) if step.kind == "header"]
        self.assertEqual([step.clears for step in headers], [True, True, True])

    def test_the_intro_header_holds_while_it_is_discussed(self):
        # The `clear` that follows the intro task list must stay a separate
        # press, or the list is wiped before it can be talked through.
        steps = parse(self.SOURCE)
        intro = next(step for step in steps if step.kind == "header")
        following = steps[steps.index(intro) + 1]
        self.assertEqual(following.kind, "header")
        self.assertEqual(following.lines[0], "1. Write the script")

    def test_the_note_rides_with_the_command_it_describes(self):
        step = next(
            step
            for step in parse(self.SOURCE)
            if step.kind == "arm" and step.text.endswith("etc_backup.sh")
        )
        self.assertEqual(step.notes, ("run it by hand before trusting it to a schedule",))


class NoEnterBinding(unittest.TestCase):
    """`#@ noenter` may bind only to a command.

    A command is the only step an Enter can belong to. Allowing the directive
    to bind elsewhere let it carry past that construct and strip the Enter from
    the next real command, which produced a recording showing a command typed
    and never run.
    """

    def test_a_command_gets_its_enter_without_being_asked(self):
        self.assertEqual(
            [(s.kind, s.text) for s in parse(":wq\n")[:2]],
            [("arm", ":wq"), ("run", ":wq")],
        )

    def test_noenter_makes_a_command_a_single_send(self):
        self.assertEqual(parse("#@ noenter\nq\n")[0].kind, "send")

    def test_noenter_arguments_are_refused(self):
        with self.assertRaisesRegex(
            CommandFileError, r"^line 2: noenter takes no arguments$"
        ):
            parse("pwd\n#@ noenter unexpected\nq\n")

    def test_noenter_allows_trailing_whitespace(self):
        self.assertEqual(parse("#@ noenter \t\nq\n")[0].kind, "send")

    def test_noenter_before_a_header_is_refused(self):
        with self.assertRaises(CommandFileError):
            parse("#@ noenter\n#^ Header\nls\n")

    def test_noenter_before_a_merging_clear_is_refused(self):
        # The clear/header merge is the other path the directive leaked through.
        with self.assertRaises(CommandFileError):
            parse("#@ noenter\nclear\n#^ Header\nls\n")

    def test_noenter_at_end_of_file_is_refused(self):
        with self.assertRaises(CommandFileError):
            parse("ls\n#@ noenter\n")

    def test_a_clear_that_does_not_merge_still_accepts_one(self):
        self.assertEqual(parse("#@ noenter\nclear\nls\n")[0].kind, "send")

    def test_pause_before_a_header_remains_valid(self):
        self.assertEqual(parse("#@ pause 12\n#^ Header\n")[0].pause, 12.0)

    def test_pause_before_a_merging_clear_remains_valid(self):
        step = parse("#@ pause 70\nclear\n#^ Header\n")[0]
        self.assertTrue(step.clears)
        self.assertEqual(step.pause, 70.0)


class PauseValidation(unittest.TestCase):
    def test_a_negative_hold_is_refused(self):
        with self.assertRaises(CommandFileError):
            parse("#@ pause -5\nls\n")

    def test_a_non_finite_hold_is_refused(self):
        for value in ("nan", "inf", "-inf"):
            with self.subTest(value=value), self.assertRaises(CommandFileError):
                parse(f"#@ pause {value}\nls\n")

    def test_zero_is_allowed(self):
        self.assertEqual(parse("#@ pause 0\nls\n")[1].pause, 0.0)

    def test_a_pause_binding_to_nothing_is_refused(self):
        with self.assertRaises(CommandFileError):
            parse("ls\n#@ pause 5\n")

    def test_an_unknown_directive_is_still_refused(self):
        with self.assertRaises(CommandFileError):
            parse("#@ pasue 8\nls\n")


if __name__ == "__main__":
    unittest.main()
