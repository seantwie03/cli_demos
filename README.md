# Command Line Demonstrations with Kitty

Many of us in the IT industry have probably had professors that type very, very slowly. Or worse, professors that make a lot of typos. Those can really throw off a demonstration as the professor has to go into troubleshooting mode to figure out why their command didn't work. This project was created to avoid all these problems.

Write a "command file" listing every command the demonstration runs. During the
demo, one key puts the next command on the prompt as if it had been typed by
hand. Explain it to the audience, press the same key again to run it, and repeat
until the demonstration is complete. The terminal stays fully live the whole
time, so a question can always be answered with an ad-hoc command.

[![asciicast](https://asciinema.org/a/706500.svg)](https://asciinema.org/a/706500)

To see a sped up demonstration using this tool check my [Asciinema profile](https://asciinema.org/~sean-twie03).

## Setup

Requires Linux, [Kitty](https://sw.kovidgoyal.net/kitty/), Python 3.9+, and
`stty`. The Python package has no third-party dependencies. Recording also
requires Bash, asciinema 3, and Linux pidfd support (kernel 5.3+).

1. Clone this repository, and put `kitty-demo.py` somewhere on your `PATH`:

   ```
   ln -s /path/to/cli_demos/kitty-demo.py ~/bin/kitty-demo
   ```

2. Add these settings and presentation controls to your `kitty.conf`, then start
   a new Kitty instance (reloading does not apply `listen_on`):

   ```kitty.conf
   allow_remote_control socket-only
   listen_on unix:${XDG_RUNTIME_DIR}/kitty-demo-{kitty_pid}

   # F1 back, F2 performs the selected action, F3 forward.
   map f1 remote_control send-text --match 'title:Controller' 'back\n'
   map f2 remote_control send-key --match 'title:Controller' enter
   map f3 remote_control send-text --match 'title:Controller' 'forward\n'
   map --when-focus-on title:^Controller$ page_up remote_control send-text --match 'title:Controller' 'scroll-up\n'
   map --when-focus-on title:^Controller$ page_down remote_control send-text --match 'title:Controller' 'scroll-down\n'
   ```

   This setup uses the private `$XDG_RUNTIME_DIR` supplied by a Linux desktop
   login session. No directory creation, login scripts, or manual environment
   exports are needed inside Kitty. Kitty creates the pathname Unix socket and
   passes its address to child processes as `KITTY_LISTEN_ON`. Socket access
   permits control of the instance; the private directory restricts other users,
   but does not isolate processes running as your own user.

   There is no mapping to start a demonstration: the script names its own window `Controller` when it runs, so
   it can be started by hand from any Kitty window.

3. Write a [command file](#command-file-syntax).
4. Run it, then press your advance key to step through it.

```
kitty-demo path/to/command_file.sh            # live, for class
kitty-demo --record path/to/command_file.sh   # unattended, writes a .cast
kitty-demo --check path/to/command_file.sh    # validate only
```

The window you start it in becomes the Controller for the duration and gets
its title and your prompt back when the demonstration ends. Open a split first
if you want to keep a shell alongside it.

For optional `--record` invocation outside Kitty, obtain the intended instance's
address by running `printf '%s\n' "$KITTY_LISTEN_ON"` in one of its shells.
Pass that complete address to the external caller, for example:

```sh
KITTY_LISTEN_ON='unix:/run/user/1000/kitty-demo-12345' kitty @ ls
KITTY_LISTEN_ON='unix:/run/user/1000/kitty-demo-12345' kitty-demo --record path/to/command_file.sh
```

The user ID and PID above are examples; use the actual reported address and
refresh it after restarting Kitty. Do not select an arbitrary socket when
multiple instances exist. Schedulers also need this address and a running
Kitty instance. Interactive live mode should start inside Kitty so the
Controller receives its mapped keys. An unavailable endpoint produces a
startup error; `--check` works without Kitty.

With `socket-only`, both `send-key` and `send-text` use the inherited socket
address; terminal remote-control requests are denied. See [Kitty listener
configuration](https://sw.kovidgoyal.net/kitty/conf/#opt-kitty.listen_on) and
[socket invocation](https://sw.kovidgoyal.net/kitty/remote-control/#remote-control-via-a-socket).

## Recording and window placement

`--record` uses an interactive Bash login shell, advances on the configured
pauses, and records at 120×24. At completion, a supervisor ends the recorded
shell with SIGHUP and waits for asciinema to exit successfully before closing
the owned Presentation window and replacing the destination cast. This verifies
recording finalization; it does not detect whether each demonstrated command
finished successfully. Give long-running commands sufficient pauses.

Each attempt writes a unique `*.cast.<random>.partial` file beside the command
file. Startup, playback, shutdown, or publication failure preserves the previous
cast and reports the retained partial's pathname. A retry uses a new pathname.
Forced recorder termination is a failure, never a successful publication.
Ctrl-C follows the same cleanup path. Live mode leaves a successfully launched
Presentation open for questions, including after interruption.

KDE Plasma 6 and Niri automatically place the Presentation on the next active
output by connector-name order, relative to the output active before launch.
With two monitors this is the other monitor; with one it stays there and is
maximized. KDE verifies output and maximization through a temporary KWin script,
then unloads it. No permanent window rules or extra KDE setup are needed.
KDE uses `gdbus`; Niri retains its helper and `jq` dependency. If placement is
unavailable or times out, a warning is printed and the demo continues where the
window opened. On other desktops, ordinary window placement applies.

Niri's maximize-column action operates on focus: the helper explicitly focuses
and checks the new window first, but a simultaneous focus change can still race
that final action. KDE targets the specific window throughout. Physical
multi-monitor KDE movement and the updated Niri helper still need rehearsal;
KDE single-monitor maximization and recording have been verified.

## How it works

Two windows. The **Controller** is the window you started the script in: it
shows what the next press will do and displays presenter notes the audience
never sees. The **Presentation** window is opened by the script and is what the
audience watches.

The advance key is a Kitty mapping that sends Enter to the Controller. The
script reads it and drives the Presentation window over [Kitty's remote
control](https://sw.kovidgoyal.net/kitty/overview/#remote-control), so it works
after `sudo`, across `ssh`, and inside full-screen programs such as `vim` and
`less`.

F2 does all normal advancement: the first press puts a command on the prompt,
the second runs it. A section header takes one press; presenter notes take none.

### The Controller display

The Controller uses the terminal's full available height and adapts when you
resize it. The list aims to show five items before and five after the current
item. Commands occupy one row through both typing and submission; headers are
also selectable items. Only the selected row has an action label, in the left
column.

```
sample_command_file.sh · item 5/17 · line 10
──────────────────────────────────────────────────────────────────────
          HEADER: 1. Inspect the current working directory
          NOTE: Explain what the working directory means.
          pwd
 [ENTER]  ls
          HEADER: 2. Inspect a different directory
          ls /etc/
          clear
```

The left-hand label says what the next F2 press will do: `[TYPE]`, `[ENTER]`, `[SEND]`
(keystrokes without Enter), `[KEY]` (a key event), `[SHOW]` (a header), `[CLEAR+SHOW]` (a header with
merged clear), or `[END]`. After typing a command, the label stays beside it and
changes to `[ENTER]`. After submission, the label moves to the next item.
The status shows the command file, selected item, and source line. Record mode
adds `REC` and elapsed time; its playback sequence and pauses are unchanged.

**HEADER:** rows show only the first header line, shortened with an ellipsis
when necessary. F2 still draws the complete header in the Presentation window.
A merged `clear` is part of that header, not a separate list item.

**NOTE:** rows appear immediately before their associated item, so you can see
them coming and decide when to speak. Notes wrap and are never truncated. They
remain with the command during both typing and submission. When space is tight,
the HUD removes whole surrounding items and their notes, starting with the
farthest previous items. If the current note exceeds the screen, focus the
Controller and use PageUp/PageDown to read it. The selected command stays pinned
when there is room, and scrolling never advances the demo. These
[conditional mappings](https://sw.kovidgoyal.net/kitty/mapping/) leave those keys
unchanged in the Presentation window.

### Revisiting commands and answering questions

F1 selects backward; F3 selects forward. These keys only change the
Controller selection: they do not type, execute, clear input, or undo anything
in the Presentation window. Headers participate in navigation just like commands.
Earlier list items mean earlier in the file, not necessarily already executed.

While `[ENTER]` is pending, F1 resets the current command to `[TYPE]`.
Pressing F1 again selects the preceding item, like restarting a song and
then going to the previous song. F3 skips to the following item from either
phase.

For example, if a question arrives after F2 types `pwd`, cancel that input in
the Presentation window and run your ad-hoc commands. Return to an empty prompt,
press F1 to select `pwd` for retyping, then use F2 twice to type and run it.
If you already ran it manually, F3 skips the pending submission. You remain
responsible for restoring the expected prompt or editor state before resuming.

At completion, F2 returns to your original Controller shell; F1 revisits
the last item. Ctrl-C in the Controller also exits, and closed input stops it
without advancing. Terminal settings and the previous screen/title are restored.
The live Presentation window remains open for questions.

**Only one demonstration runs at a time.** Both windows are found by a fixed
title, and Kitty applies a remote-control command to every window that matches,
so a second session would send commands to the previous demonstration's window
and split the advance key between two controllers. Starting a second one fails
with a message naming the window to close. Live mode leaves its Presentation
window open on purpose, so this is normal between back-to-back demonstrations:
close it with `ctrl+alt+w` and start the next one.

## Command file syntax

Each line is processed in order.

| Line          | Meaning                                                        |
| ------------- | -------------------------------------------------------------- |
| `#^ Title`    | Section header, drawn full width in the Presentation window     |
| `#   detail`  | Header continuation, audience visible, until a command intervenes |
| `#! note`     | Presenter note, displayed in Controller window only                 |
| `#@ ...`      | Directive for the script, never displayed                       |
| anything else | Typed into the Presentation window                              |

```sh
#^ Inspect a file system
#   Host: servera
#! Give the audience a mnemonic for each command
pwd
ls -l
```

A bare `clear` immediately before a section header is merged into it, so a
section transition costs one press rather than three.

A `#` line means one of two things, and the line before it decides which. A
section header claims every `#` line that follows it, however the block is
spaced, so all of these are header text:

```sh
#^ Configure the service
#   Host: servera
#   Goal: serve a page
```

A command closes the section. After one, a `#` line is typed into the
Presentation window like any other line, which is what you want for a comment
the audience should read and for a commented line going into a config file:

```sh
sudo -i
# Everything below runs as root
vim /etc/motd
#@ noenter
i
# Managed by the IT-230 class
```

Use `#!` for a comment the audience should not see.


### Directives

| Directive    | Effect                                                |
| ------------ | ----------------------------------------------------- |
| `#@ pause N` | Hold N seconds after the next step. Record mode only.  |
| `#@ noenter` | The next line is keystrokes; send no Enter after it.   |
| `#@ key KEY` | Send one Kitty key specification, with no extra Enter. |

`pause` and `noenter` must be followed by the step they apply to. `key` is
itself an action: one F2 press sends the key. Notes and a pending pause apply
to that action; a pending `noenter` before it is an error.

**Why `#@ noenter` exists.** Every line gets an Enter unless it says
otherwise. That is right at a shell prompt, and right for most lines inside an
editor too, because there the Enter is the newline: a body line being inserted
needs one, and so does `:wq` after leaving insert mode with `#@ key escape`.
The exceptions are keystrokes that finish the
moment they arrive, such as `q` leaving a pager or `dd` deleting a line. Those
need marking, or the Enter lands somewhere it was not wanted.

```sh
less /var/log/cron
#@ noenter
G
#@ noenter
q
ls -l /tmp
```

Use `#@ key` for combinations such as Ctrl-X. For example:

```sh
nano demo.txt
A note for this demonstration.
#@ key ctrl+x
y
```

One F2 sends Ctrl-X. On the plain `y` line, F2 types `y` to answer the save
prompt, then the next F2 sends Enter to confirm the filename.

The argument uses [Kitty's send-key syntax](https://sw.kovidgoyal.net/kitty/remote-control/#kitten-send-key)
directly, preserving case and internal whitespace. Use one key specification
per directive, with separate directives for successive key presses. There is
no translation of literal text such as `^X` into control keys.
`--check` rejects a missing key argument but leaves key-name validation to
Kitty. Delivery depends on the application's keyboard mode; Kitty may report
success even when it cannot deliver a key. Rehearse the interaction in the
target application and annotate any literal text needing `#@ noenter` by hand.

## Validating command files

```
kitty-demo.py --check path/to/command_file.sh   # one file
tools/validate_command_files.py path/           # a whole directory
```

Both use the same rules, so a file that passes one passes the other. They exit
nonzero when a file fails to parse.

Validation is not something you have to remember. Every run parses the command
file first and refuses to go further if it cannot, before a window opens, a
session is claimed, or a recording starts. `--check` is the same validation on
its own, for when you want it without starting a demonstration.

## Development

Every script carries a shebang and is executable, so they run directly. To
reach them from anywhere, put one symlink on your `PATH`:

```
ln -s ~/s/cli_demos/kitty-demo.py ~/bin/kitty-demo
```

Python resolves the symlink when locating the package, so the import works
through it.

```
python3 -m unittest discover -s tests -t .
```

`sample_command_file.sh` doubles as a worked example and as the fixture the
focused tests exercise.

## Thanks

Thanks to [Kovid Goyal](https://sw.kovidgoyal.net/kitty/support/) for making such an awesome terminal program!

## Other implementations

`kitty-demo.sh` is the original Bash implementation. It is **deprecated** and
kept only so an older demonstration can still be replayed; `kitty-demo.py`
replaces it. It does not support directives, one-key advancing, record mode, or
validation, and it writes its recordings under `/tmp`.

Two further variants live on other branches. Both are simpler and need only
Bash, at the cost of real limitations.

### Readline

**Branch**: [readline](https://github.com/seantwie03/cli_demos/tree/readline?tab=readme-ov-file)

Uses Bash functions to manipulate `readline`. Very simple. Does not work when
escalating to `root` or switching users, and does not work in full-screen
programs such as `vim` or `parted`.

### Readline Multi-User

**Branch**: [readline-multi-user](https://github.com/seantwie03/cli_demos/tree/readline-multi-user?tab=readme-ov-file)

Similar, but available to every user on the system, so the keyboard shortcut
keeps working after escalating to `root` or switching users. Still does not work
in full-screen programs.
