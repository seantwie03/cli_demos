# Python rewrite review

Reviewed the working tree on 2026-09-12, including the Python entry point, package, tools, tests, README, and changes to the original Bash script. Updated on 2026-09-13 after implementing Findings 2 and 4 together, following Finding 1's snapshot-based fix. Original diagnoses and design proposals are retained as history; older numeric source references may have shifted with the implementation.

**Current status:** Finding 1 is fixed within the accepted snapshot/timing limitations. Finding 2 is fixed. Finding 4 now has the agreed explicit navigation/recovery workflow and full-height HUD; manual terminal state remains the presenter's responsibility. Finding 5 is partially addressed. Findings 3 and 6–12 remain open. The smaller display-content issue is resolved, and several documentation/completion messages were corrected with the HUD update.

## Overall assessment

The basic direction fits your goals: a command-file argument eliminates editing the launcher, the executable plus a PATH symlink is sufficient deployment, and an explicit sequence of type/run steps makes F2 advancement straightforward. Keeping a real presentation terminal preserves SSH, sudo, TUIs, and manual commands. The pure parser and standard-library-only implementation are useful choices worth keeping.

The largest remaining problems are in command transport and recording lifecycle, not the parser architecture. The navigation and input changes keep parsing separate from terminal effects, and the HUD now renders logical command rows from that same step sequence. Fixed window titles and personal recording preferences remain useful simplification targets.

Ad-hoc commands still work between completed demo commands. After canceling an already typed command, the presenter can now use F1 to select it for retyping or F3 to skip it. This is explicit recovery rather than automatic shell/editor-state detection; the README documents restoring the expected prompt or application state before resuming.

Severity: **P1** means a core workflow can fail or behave materially differently from what the presenter sees; **P2** means a reproducible correctness or reliability issue; **P3** means a smaller validation, documentation, or maintenance issue. Findings identified as inherited are still worth addressing, but are not new regressions.

## Findings

### 1. Resolved (originally P1) — Recording terminal discovery selected the unrecorded outer PTY

**Current fix location:** `kittydemo/driver.py:180–193, 235–264`. The diagnosis below describes the removed `discover_tty()` implementation, originally at lines 180–209 and called at line 270.

The old `discover_tty()` assumed that Kitty's `foreground_processes` included the shell inside asciinema. That list does not describe the entire descendant process tree. The installed Kitty implementation obtains the foreground process group of its own PTY and lists that group's processes (`/usr/lib64/kitty/kitty/child.py:560–566`). Asciinema's recorded child has a different controlling PTY and process group.

I reproduced this with an isolated asciinema 3.0.0 process under a PTY, recording `sleep 3`. The recorder's stdin was `/dev/pts/0`; its recorded child used `/dev/pts/1`. Supplying the corresponding Kitty-style foreground listing to `discover_tty()` returned `/dev/pts/0`.

Consequently, `Session.write()` drew headers outside the recorded stream. The audience could see them in the live terminal while the cast omitted them. Width measurements also came from the outer terminal rather than the fixed recording dimensions. Asciinema captures output through its own PTY, as described in its [recording architecture](https://docs.asciinema.org/how-it-works/).

**Resolution:** The selected fix compares PTY snapshots and requires exactly one new entry, as described in the second subsection below. The initial handshake recommendation is retained for reference only; it is not outstanding work or a prerequisite for resolving this finding.

#### Unselected proposal: report the recorded shell's TTY

**Status:** The original defect was confirmed by replaying `sample_command_file.sh`. This proposal was not selected because of its added complexity; the simpler snapshot approach below was implemented instead. References to `discover_tty()` in this proposal describe the pre-fix code.

Use a small file-based handshake between the controller and the shell running **inside asciinema**. This identifies the correct terminal directly and avoids walking process trees or guessing from newly created `/dev/pts` entries.

1. **Create per-run handshake storage.** In the recording launch path, create a `tempfile.TemporaryDirectory` and choose a `tty-ready` path inside it. Keep the directory alive until startup has succeeded or failed. Pass its absolute path to the recorded shell through a dedicated environment variable such as `KITTY_DEMO_TTY_READY`. A unique directory prevents a previous run's response from being accepted.

2. **Start asciinema as the Presentation window's actual process.** Build the Kitty launch arguments with `asciinema rec ... --command <recorded-shell-command>`, instead of launching an outer login shell and typing the recorder command into it. Preserve the `.partial` output destination and current recording dimensions. Quote the command string with `shlex.join()` because asciinema's `--command` accepts a command string, while passing the surrounding Kitty launch arguments as a subprocess argument list. Capture the returned Kitty window ID for startup checks and failure cleanup.

3. **Publish the TTY at the end of shell initialization.** For the existing Bash-oriented recording setup, use an explicit interactive Bash invocation with a temporary `--rcfile`. That startup file should load the intended Bash configuration, apply the existing recording prompt setup, and then publish its stdin terminal. Make Bash an explicit recording dependency rather than passing Bash initialization to an arbitrary `$SHELL`. Keep this setup limited to record mode; normal live mode can continue using the user's configured shell. The final startup action can use:

   ```bash
   tty > "${KITTY_DEMO_TTY_READY}.pending" &&
       mv -- "${KITTY_DEMO_TTY_READY}.pending" "$KITTY_DEMO_TTY_READY"
   ```

   Here `tty` inherits the recorded shell's stdin, so it reports asciinema's inner PTY. The temporary-file rename prevents the controller from reading an incomplete pathname. The response goes to the private file, not the recorded screen. Do not run this handshake in the controller or an outer shell, and do not publish it in a wrapper *before* shell initialization. Decide which existing Bash startup files to load explicitly so aliases and other demo requirements are preserved; do not accidentally source them twice.

4. **Wait for the response with a deadline.** Replace the recording-startup sleeps with a short polling loop using `time.monotonic()` and a bounded timeout, for example ten seconds. Check that the launched window still exists while waiting. Read the published pathname, open the existing device without a create/truncate mode, and verify it is a terminal with `os.isatty()`. On timeout, invalid response, or early window exit, fail before playing any demo steps and close only the window created by this launch. Never fall back to the outer PTY. Reaching this startup hook establishes terminal identity and completion of the chosen initialization; it does not establish that subsequent SSH commands, installations, or TUIs have finished.

5. **Use that pathname as `Session.tty_path`.** Both `Session.write()` and `Session.width` will then operate on the recorded terminal. Retain the current Kitty input path for commands and keys: asciinema forwards that input to its child. Only record mode needs to stop calling the current `discover_tty()` implementation for this fix. A later change can unify live-mode discovery if useful; it is not required to restore recorded headers. Clean up handshake files after startup, including failure paths.

6. **Verify the output, not just the selected pathname.** Add a focused test with a real recorder and a harmless short-lived child that reports its PTY. Write a unique header marker through `Session.write()`, finish the recorder, concatenate the cast's output events, and assert that the marker was captured. Test timeout and early-exit paths too. Finally repeat the user's reproduction with `sample_command_file.sh`: all four section headings must be present in the cast as well as visible during playback, and live mode must still allow manual commands between completed steps.

This fix can reuse the existing `Session` and header renderer. It needs no new command-file directives, extra presentation keys, or shell-prompt detection. Verified recorder shutdown and publication remain the separate lifecycle work described in Finding 6.

#### Implemented fix: compare `/dev/pts` before and after startup

Port the Bash script's snapshot-and-difference approach. This is a smaller fix for a controlled presentation environment: no handshake files, custom shell startup, or process-tree inspection.

The Bash implementation snapshots `/dev/pts`, launches the Presentation window and recorder, waits, and selects an entry that appeared afterward (`kitty-demo.sh:60–82`). For Python, make one small adjustment: **in record mode, take the snapshot after the Presentation window exists but immediately before starting asciinema.** That excludes the outer PTY from the difference, leaving the recorder's inner PTY as the expected new entry. In live mode, take the snapshot before launching the Presentation window, since its outer PTY is the one we want.

The discovery logic can be this small:

```python
def tty_paths() -> set[Path]:
    return {p for p in Path("/dev/pts").iterdir() if p.name.isdigit()}


def new_tty(before: set[Path]) -> Path:
    created = tty_paths() - before
    if len(created) != 1:
        raise RuntimeError(
            f"Expected one new presentation TTY, found {len(created)}; "
            "retry without opening other terminals during startup"
        )
    return created.pop()
```

**Integration:** `launch()` now takes `before = tty_paths()` before window creation for live mode and replaces that snapshot immediately before starting asciinema in record mode. The final `new_tty(before)` result becomes `Session.tty_path`. Record mode checks the outer terminal through the existing window/PID lookup and verifies it is in the snapshot. The current delays, command sending, shell selection, prompt setup, and header rendering remain in place. If slow startup proves troublesome, a future small improvement could retry an empty difference for a short bounded interval instead of increasing a fixed sleep indefinitely.

**Why require exactly one entry?** The Bash script selects the last entry from a text-sorted difference. When both the outer and inner PTYs are new, that ordering does not establish which belongs to the recorder: `/dev/pts/9` sorts after `/dev/pts/10`. Moving the recording snapshot between the two launches avoids needing that guess. Rejecting an ambiguous difference also prevents casually choosing another terminal when multiple new devices appear.

**Accepted tradeoff:** This remains a timing-based heuristic. Another terminal, recorder, or background PTY allocation during startup can cause ambiguity; if the intended PTY never appears and exactly one unrelated PTY does, it can still select the wrong device. A pathname snapshot also cannot detect a device being removed and recreated under the same name. For the usual single-demo workflow with no concurrent terminal creation, these may be reasonable limitations in exchange for the smaller implementation. This detects a new device, not shell readiness or recording completion.

**Implementation status:** This alternative has now been implemented in `kittydemo/driver.py`. Recording startup verifies the outer PTY is present before taking its snapshot; both modes require exactly one new device. The existing fixed startup delays are retained, with a short delay before the outer-terminal check. The handshake alternative above remains unapplied.

**Verification:** All 63 automated tests pass, including seven new driver tests covering real PTY selection, numeric-entry filtering, zero/multiple candidates, live/record snapshot placement, missing outer PTY, and refusal to fall back to it. An isolated asciinema recording selected `/dev/pts/1` while its outer terminal was `/dev/pts/0`, measured the configured 120-column width, and captured a unique header written through `draw_header()`. Existing Kitty windows and the user's sample recording were not touched. A full graphical replay of the sample remains a useful final rehearsal: all four headings should now be captured.

### 2. Resolved (originally P1) — Ctrl-C was swallowed while waiting for F2

**Current implementation:** `kittydemo/driver.py`, `Requests`; `kitty-demo.py`, `main()` and `play()`. The diagnosis below describes the removed `Advance` implementation.

`tty.setraw()` disables terminal-generated signals. Ctrl-C arrives as `\x03`, which `wait()` discards because it accepts only carriage return and newline. Ctrl-D is also discarded. This removes the normal way to stop a foreground command launched from a shell and can strand the instructor in the controller until they finish the demonstration or kill it another way.

A PTY probe confirmed that Ctrl-C leaves `Advance.wait()` running; a subsequent Enter completes it. This is a regression from Bash's normal `read` behavior.

The non-terminal path has a related problem: EOF produces `""`, which `wait()` retries forever. Starting with stdin closed therefore spins instead of exiting. A subprocess probe remained running after its stdin was set to `/dev/null`.

**Recommendation:** Since the mapping already sends Enter, prefer ordinary line input and handle EOF/KeyboardInterrupt. If character input is retained, enter cbreak mode once, preserve signal handling, and explicitly terminate on EOF. There is no implemented second single-character control that justifies switching raw mode on and off for every character.

#### Suggested implementation: fix alongside Finding 4's HUD and navigation update

**Status:** Implemented alongside [Finding 4's HUD/navigation update](#suggested-implementation-f1-back-f2-execute-f3-forward). `Requests` keeps canonical input and terminal signals enabled, disables echo for the session, restores saved attributes on exit, and raises EOF rather than retrying indefinitely. `main()` reports interruption without a traceback (status 130) and input closure as an incomplete run (status 1). The implementation contract below was used for both changes.

Replace `Advance`'s raw-byte reader and debounce loop with the line-based request reader needed for the navigation mappings. A blank line advances, `back` selects backward, and `forward` selects forward. Each Kitty mapping supplies its terminating Enter/newline, so normal advancement still requires only F2. Leave the Controller terminal in its normal signal-enabled input mode; remove the per-character `tty.setraw()`/terminal-restoration calls.

With normal terminal handling, Ctrl-C in the focused Controller raises `KeyboardInterrupt`. Catch it at the CLI boundary after the existing cleanup `finally` blocks have unwound, return an interrupt exit status (130), and avoid an unnecessary traceback. Restore the Controller title and release its session claim through those cleanup paths. Live-mode interruption must leave the Presentation window open and send it no extra command or keypress. Ctrl-C in the Presentation window continues to affect its own foreground program independently.

Treat EOF as an explicit controller-exit request, not an advance or another retry. If using `sys.stdin.readline()`, distinguish `""` (EOF) from `"\n"` (advance); if using `input()`, handle `EOFError`. Do not mark an interrupted or abandoned demonstration as completed. Recorder startup/shutdown reliability remains the separate work in Finding 6.

Add tests with the Finding 4 changes: Ctrl-C during a PTY-backed wait must exit and run cleanup; EOF must exit without spinning or advancing; a blank line must still advance exactly once; and back/forward requests must remain selection-only. Retest Ctrl-C while the completed-demo screen is awaiting its final press as well as during normal playback. Any input handling added for HUD scrolling must preserve these interrupt/EOF semantics.

### 3. P1 — Command text is interpreted for escapes before reaching the terminal

**Location:** `kittydemo/driver.py:267–268`.

Passing command text as the positional argument of `kitty @ send-text` does not send it verbatim: Kitty decodes backslash escapes. For example, a command-file line `printf '%s\n' hello` contains a literal backslash plus `n`, but the payload contains an actual newline inside the quoted format. Other sequences can send tabs, carriage returns, or control bytes during the supposedly type-only press. This damages shell examples and editor content and can defeat the separation between typing and submitting a command.

Confirmed using the installed Kitty escape parser, without sending anything to an existing window. The behavior is documented in [Kitty's send-text options](https://sw.kovidgoyal.net/kitty/remote-control/#kitten-send-text).

This behavior is inherited from the Bash implementation, but the rewrite's stronger one-key/type-then-run contract makes it especially important to resolve.

**Recommendation:** Send ordinary command text through `send-text --stdin` using `subprocess.run(input=text, ...)`, which preserves the payload. Audit any existing files that deliberately rely on escaped control codes before changing this. If scripted special keys are needed, give them an explicit representation rather than decoding all command text.

### 4. Addressed (originally P2) — Explicit navigation recovers from a stale pending run action

**Current implementation:** `kittydemo/controller.py`, `Cursor`; `kitty-demo.py`, `play()`; `kittydemo/hud.py`, `render()`. The original limitation below explains why the new recovery controls are needed; navigation still does not inspect or clear terminal input.

The controller walks a precompiled list and never observes manual activity in the Presentation window. After F2 types `pwd`, canceling that line with Ctrl-C and answering a question does not cancel the controller's pending `run(pwd)` step. The next F2 sends only Enter; it cannot restore `pwd`. The step is consumed even though the advertised command was never run. If a detour leaves a different command partly typed, that command is what F2 submits, despite the HUD displaying the old one.

This does **not** mean arbitrary commands are generally broken. They work when you detour at an empty prompt between completed steps, and manually executing the armed command then returning to an empty prompt usually causes only an extra blank Enter. The failure is specifically cancellation/replacement of armed input or returning in a different application state.

**Recommendation:** Document a simple detour convention: complete the current type/run pair, answer the question, restore the expected prompt/application state, then resume. For interruptions that cannot wait, offer a small explicit re-arm/reset action if you need it. An exceptional recovery action does not require a second key for normal advancement. Avoid inferring state from prompt text or injecting automatic Ctrl-U/Ctrl-C into arbitrary TUIs.

#### Suggested implementation: F1 back, F2 execute, F3 forward

**Status:** Implemented with the agreed labels, header/command navigation, full-height HUD, inline notes, Controller-only note scrolling, non-echoing input, and resize handling. The specification below records the intended behavior. The new mappings are documented in the README and must be added/reloaded in the user's Kitty configuration; that configuration was not changed by this implementation.

**Define navigation as selection only.** F1 and F3 change the next action shown in the Controller; they send nothing to the Presentation window. F2 remains the key that actually types, submits, or draws the selected step. Moving backward does not undo an executed command, and moving forward does not execute skipped commands. The presenter must clear any abandoned input and restore the expected shell/editor state before resuming. This preserves arbitrary manual commands without assuming how to clear input in Bash, SSH, Vim, or another program.

**Key mappings and input:** Use F1 for back, F2 for the selected action, and F3 for forward. Replace the previous three navigation mappings with these; the underlying controller requests are unchanged:

```kitty.conf
map f1 remote_control send-text --match 'title:Controller' 'back\n'
map f2 remote_control send-key --match 'title:Controller' enter
map f3 remote_control send-text --match 'title:Controller' 'forward\n'
map --when-focus-on title:^Controller$ page_up remote_control send-text --match 'title:Controller' 'scroll-up\n'
map --when-focus-on title:^Controller$ page_down remote_control send-text --match 'title:Controller' 'scroll-down\n'
```

Here the newline escape is deliberately interpreted by Kitty's `send-text`, terminating the controller request. These messages are separate from verbatim demo-command transport discussed in Finding 3. All three mappings target the Controller even when the Presentation window has focus. The existing title-matching limitation in Finding 9 remains separate.

The PageUp/PageDown mappings apply only while the Controller is focused, using Kitty's [conditional mappings](https://sw.kovidgoyal.net/kitty/mapping/). They send viewport-scroll requests without changing the selected item or consuming an F2 action. In the Presentation window those keys retain their normal behavior.

While reading requests, disable terminal echo but preserve canonical line input and signal handling. Restore the saved terminal attributes on every exit path. Watch for terminal dimension changes while waiting for input and request a HUD redraw without advancing; a short timed `select()` wait can detect resizing without adding signal handlers. Preserve partially received requests across resize redraws. These changes are part of the shared implementation for Findings 2 and 4.

Replace `Advance.wait()` with a small request reader: a blank line means `advance`, `back` means `back`, and `forward` means `forward`; ignore other lines. Use normal line input, handle EOF by ending the controller, and allow Ctrl-C to interrupt it. This also addresses Finding 2 without adding function-key escape-sequence parsing or raw-mode handling. Do not carry over the timing debounce: silently dropping a navigation request would make the displayed position unpredictable. The two new shortcuts still work immediately because their mappings send the newline for the user.

**Cursor rules:** Keep the parser's existing flat `Step` list. Build a list of navigation stops at `arm`, `send`, `header`, and `end` steps. An `arm`/`run` pair is one command; `run` is never a navigation destination. Headers count as standalone stops so sections can be revisited, and `#@ noenter` lines remain single stops. Notes and directives do not add stops.

Replace `for index, step in enumerate(steps)` in live playback with a cursor-controlled loop. The cursor identifies the next F2 action. Navigation selects the previous or next stop strictly before or after that cursor, clamping at the first and final stops. For example, use `bisect_left(stops, index) - 1` for back and `bisect_right(stops, index)` for forward, with bounds checks. F2 performs the current step and advances one position exactly as it does today.

| Current next action | F1 | F3 |
| --- | --- | --- |
| Type command B (`arm`) | Select preceding stop A | Select following stop C |
| Submit already typed B (`run`) | Select B's `arm` again | Select following stop C |
| Send immediate keystrokes or draw a header | Select preceding stop | Select following stop |
| Final `end` step / completion screen | Select last real stop | Stay at the end |

The `run` case follows directly from navigating command starts: B's `arm` is the preceding stop. Like a music player's Back button, the first press restarts the current item and the second selects the preceding item. In the HUD, the first press changes `[ENTER]` to `[TYPE]` in the same left-hand action column. At a boundary, navigation still must not type or execute anything.

**Header navigation:** Headers participate exactly like commands. If the preceding stop is a header, F1 selects it; another F1 selects the stop before that header. Selection alone does not redraw it. F2 on the selected header redraws its full audience-visible content, including continuation lines, and performs its merged `clear` if present.

**Recovery example:** F2 types `pwd`; a student asks a question; the presenter cancels that input and runs manual commands. Once back at an empty prompt, F1 selects `pwd` for typing again. F2 types it and the next F2 submits it. If the presenter already ran `pwd` manually and wants to skip the pending submission instead, F3 selects the following stop. This resolves the stale controller action through an explicit choice; it cannot automatically reconcile manual terminal state.

**Full-height HUD list:** Replace the separate ON DECK/THEN display with a single list using the existing Controller terminal's full available height. Aim for five preceding selectable items, the selected item, and five following items. These are positions in the command file, not an execution history: earlier items may have been skipped, and revisited commands may have already run. Do not resize or maximize the OS window. Measure the available terminal dimensions on each redraw so the layout adapts after resizing, allowing space for a compact status line and key hints.

Each command gets one row. Its `arm` and `run` steps share that row, with the selected action label remaining in the left column during both phases. Do not add separate Enter rows. Show exactly one action label, on the selected row, describing what the next F2 press will do. Use these labels for the selected item:

| Item / pending phase | Label |
| --- | --- |
| Ordinary command, ready to type | `[TYPE]` |
| Selected command, waiting to submit | `[ENTER]` |
| `#@ noenter` keystrokes | `[SEND]` |
| Section header | `[SHOW]` |
| Section header with merged `clear` | `[CLEAR+SHOW]` |
| Final sentinel step | `[END]` |

Unselected items have no action labels, including previous/following commands and headers. The list can look like this (shortened for illustration):

```text
    pwd
    ls -l
    HEADER: Inspect another directory…
    NOTE: Explain why this directory matters.
 [ENTER]  cd /etc
    ls
    NOTE: Ask which files they recognize.
    clear
    HEADER: Edit a script…
```

After F2 submits `cd /etc`, the sole action label moves to `ls`:

```text
    cd /etc
 [TYPE]  ls
```

**Header rows:** Prefix every section-header row with `HEADER:`, matching the `NOTE:` prefix used for speaker notes. These prefixes identify item types and remain visible on unselected rows; the next-F2 action label still appears only on the selected row, in the left column reserved for selection. After `HEADER:`, show only the title from the `#^` line. Truncate the title with an ellipsis to fit the row after reserving space for the prefix and action-label column; the character limit is determined by available width rather than a fixed constant. Keep that column blank for unselected items so titles do not change length merely when selection moves. Do not include subsequent header-continuation `#` lines in the list. A merged `clear` has no separate row: when selected, `[CLEAR+SHOW]` conveys that F2 will clear and show the header. A standalone `clear` retains an ordinary command row and shows `[TYPE]`/`[ENTER]` only when selected. The `HEADER:` prefix is HUD-only and is not sent to the Presentation terminal. This compact HUD representation does not shorten the header sent to the Presentation terminal.

**Inline speaker notes:** Show notes immediately before the selectable item to which the parser attaches them, using a distinct `NOTE:` style. Notes wrap at the available width and are never truncated or replaced with ellipses. Preserve their order and explicit line breaks. They receive no action label, do not consume keypresses, and do not count toward the five-item limits. Notes attached to an `arm` step belong to its combined command row, so they remain visible during both `[TYPE]` and `[ENTER]`. Trailing notes belong to the final item. This lets the presenter read upcoming notes and choose when to say them, including after submission while the item remains visible above the selection.

Render notes from each item's attached data instead of retaining the existing pinned-note display. Moving backward then naturally shows the notes for that position, without carrying a later note into an earlier command. If a separate section indicator is retained, derive it from the selected source position and label it as selection context; navigation does not change which header is actually on the audience's screen.

**Height and overflow:** Five items on each side is a target, not a guarantee. Lay out and measure complete item groups (all wrapped notes plus their associated row). Give the selected item and its complete notes priority. If the candidate list is too tall, remove the farthest preceding groups first, then the farthest following groups until it fits. Keep each retained note with its item; never squeeze in an item by silently dropping its note. This favors upcoming material over distant previous commands.

If the selected item's notes alone exceed the available height, provide a scrollable Controller view of that group. Preserve all note content and let the presenter reach every line; a fixed screen with clipped overflow is not sufficient. Scrolling changes only the viewport, never the demo cursor or Presentation terminal. Selecting a different item brings its row and the beginning of its notes into view where they fit together; for an oversized group, start at the beginning of the notes and keep the selected command identified in the status area. F2 remains advancement, not a note-paging key. Recompute wrapping and the surrounding-item budget when the terminal dimensions change.

**Completion and recording:** After performing `end`, retain the current completion screen and final-F2 exit behavior, but continue accepting back/forward requests there. Back clears the completion state and selects the last real stop; an empty file stays at completion. Keep unattended record playback linear and driven by the existing pauses, without reading navigation requests. It shares the new HUD renderer, but HUD navigation and note scrolling do not add recording steps or change their timing. The full-screen Controller uses the alternate screen and restores the original screen/cursor on exit, including Ctrl-C and EOF.

**Focused tests:** Verify back/forward from both `arm` and `run`, first/end boundaries, headers and noenter lines, skipping and replay selection, and navigation after completion. Assert that navigation alone makes no presentation-driver calls, that selecting a header does not draw it, and that F2 on a merged header still clears and draws its full content. Add a recovery test for the canceled-`pwd` sequence and input tests for the three request forms, EOF, and Ctrl-C.

Test that type/run share one row and label column, exactly one action label appears on the selected row, and submitting a command moves that label to the following item with the correct next action. Check that backward from `[ENTER]` changes only the pending-action label, header rows always retain their `HEADER:` prefix while omitting continuations and truncating the title appropriately, and merged/standalone clears have the correct action labels only when selected. Verify inline note association in both phases and after backward navigation, full note wrapping, five-item targets, previous-first removal of complete groups, resize behavior, and access to every line of an oversized note without advancing the demonstration. Confirm that an F2-only run and the unattended recording sequence produce the same steps as before.

### 5. P2, partially addressed — Recording startup still lacks recorder/shell readiness checks

**Location:** `kittydemo/driver.py:235–264`.

**Addressed by Finding 1:** With no unrelated PTY activity, a recorder failure that creates no inner PTY now raises `Expected one new presentation TTY, found 0` before `play()` starts. Multiple new devices are also rejected, and there is no outer-terminal fallback. The previous claim that an ordinary missing-recorder failure plays the entire demonstration into the outer shell no longer applies. A missing recording output argument also now fails before a window opens.

**Still open:** Recording starts by typing an `asciinema rec ...` command into a shell, waiting 1.5 seconds, and then sending `PS1='$ '; unset PROMPT_COMMAND PS0; clear`. The new-PTY check happens only afterward, so this setup command can still execute in the outer shell when the recorder fails. The existence of a new PTY does not establish that the recorded shell has finished initialization, that the recorder remains alive during playback, or that the cast will be finalized successfully. Slow initialization can therefore still race input delivery, and a recorder exiting after discovery is not explicitly monitored. The accepted unrelated-PTY limitations are documented under Finding 1 rather than treated as a demand to replace the chosen approach.

**Recommendation:** Keep the selected snapshot design. A small next improvement is to select the new PTY before sending prompt customization, so the zero/multiple-device failure paths send no further shell input. Document the remaining startup timing assumption, and add recorder failure reporting if rehearsal exposes a need for it. Directly launching the recorder is an optional later lifecycle simplification, not a required handshake redesign. Keep `#@ pause` as an explicit timing budget for unattended demonstrations: fixed pauses do not detect completion of SSH, package installs, or arbitrary TUI operations.

### 6. P2 — Failure paths can publish an unfinished recording or leave a session behind

**Location:** `kitty-demo.py:107–125`; `kittydemo/driver.py:383–401`.

There are three related lifecycle gaps:

- `driver.launch()` runs before the cleanup `try/finally`. If it opens a window and then fails during Niri handling, setup, or TTY discovery, teardown is never called. The new missing-outer and zero/multiple-new-PTY checks also take this path. That leftover Presentation window blocks the next attempt; Finding 1 improved error detection without fixing cleanup. The missing-output-argument check is now before launch, so that particular error no longer creates a window.
- After playback, teardown failures are warned about but `os.replace(partial, destination)` still runs and the command returns success. I reproduced this with a mocked teardown exception: publication was called and `run()` returned 0.
- `stop_recording()` uses `check=False` and discards the result. It also does not wait for the recorder to exit or finish flushing. A successful close request alone is not proof that the final recording is complete. Renaming an open file can be valid on Unix, but it is not a recorder-completion check.

The `.partial` scheme protects the previous cast only when failures are actually detected. It does not currently justify the guarantee in its comment.

**Recommendation:** Give one session owner responsibility for cleanup from the moment a window/process is created. Require verified recording completion before replacing the old cast; report unsuccessful finalization as failure. Preserve a failed partial recording when useful for diagnosis instead of automatically deleting the only evidence. Retaining atomic replacement is sensible once the completion condition is real.

### 7. P2 — Command indentation is lost, unlike the Bash implementation

**Location:** `kittydemo/engine.py:232, 284–289`; compare `kitty-demo.sh:189`.

`body = text.lstrip()` is appropriate for recognizing markers, but the parser also emits `body` as the command payload. The Bash script sends the original `cmd`.

For this valid command file:

```sh
cat <<EOF
    indented
EOF
```

the Python parser emits `indented` with no leading spaces. This changes here-document content and can break Python/YAML/Makefile examples entered in an editor. The existing `test_indentation_does_not_change_meaning` actually locks in this regression by equating the complete parsed sequences.

**Recommendation:** Classify using a stripped view, but preserve the original line for emitted text. Test indentation recognition separately from payload preservation. Blank-line removal is an existing format limitation too; document it and add an explicit way to send a blank line only if your exercises need one.

### 8. Resolved — Explicit key steps

The authoring heuristic and its usage instructions have been removed. Literal text still uses the normal type/Enter pair, or `#@ noenter` when it should arrive without Enter.

#### Implemented: explicit Kitty key steps

`#@ key KEY` is a complete action. One F2 press sends its argument through [Kitty's send-key](https://sw.kovidgoyal.net/kitty/remote-control/#kitten-send-key), with no extra Enter. For example:

```sh
nano demo.txt
A note for this demonstration.
#@ key ctrl+x
y
```

One F2 sends Ctrl-X. The plain `y` line then uses the normal pair: F2 types `y` to answer the save prompt, and the next F2 sends Enter to confirm the filename.

**Argument handling:** The parser preserves case and internal whitespace, trimming only surrounding whitespace. The driver passes the argument as one key specification using `kitty @ send-key --match MATCH -- KEY`. There is no key-name table or conversion of caret notation into control bytes. Use separate directives for successive key presses. A missing argument produces a source-line error; `--check` leaves validation of key names to Kitty. Delivery depends on the application's keyboard mode, and Kitty may report success without delivering a key.

**Parser and playback:** Key steps consume pending notes and pauses, then reset that state. Pauses apply after delivery in record mode only. A pending `#@ noenter` before a key step is rejected because the step already sends no extra Enter. Consecutive keys and a final key are supported. Keys prevent a preceding `clear` from merging across them into a header.

**Navigation and HUD:** Key steps use the existing navigation stops. Selection and revisiting do not send anything until F2 is pressed. The selected row shows `[KEY]` in the left action column and the key specification as its text. Notes and scrolling use the same behavior as other items. Live and record playback share the same key actions.

**Verification:** Tests cover argument preservation, missing arguments, note/pause binding and reset, redundant noenter rejection, consecutive/final keys, clear/header boundaries, exact subprocess arguments, the nano sequence without extra Enter, selection-only navigation, and `[KEY]` rendering. The live/record sequence test includes key steps and their pauses. A separate real nano rehearsal in an isolated PTY confirmed that Ctrl-X, plain `y`, then Enter saves the expected file and exits. This checks nano's interaction; end-to-end delivery through a graphical Kitty window remains a manual rehearsal.

### 9. P2 — Singleton machinery is racy and imposes unnecessary window cleanup

**Location:** `kittydemo/driver.py:60–61, 102–144, 216, 267–272`.

The PID file is a check-then-write sequence, not an atomic lock. Two simultaneous starts can both pass the window/PID checks, overwrite the PID file, and launch identically named presentation windows. Title-based sends then reach both. A stale PID reused by an unrelated process can also incorrectly block startup.

The global home-directory PID file blocks independent Kitty instances even though their remote-control targets may be separate. Conversely, the documented claim that both Controller and Presentation windows are checked is inaccurate: the window check examines only Presentation titles. The F2 mapping matches the unanchored expression `title:Controller`, including unrelated windows whose titles contain that word.

Even during ordinary sequential use, keeping the previous Presentation open for questions requires manually closing it before the next demonstration. That restriction exists because the launcher discards the new window ID, not because a demonstration intrinsically needs exclusive ownership of every Presentation-titled window.

**Recommendation:** Store the ID returned by `kitty @ launch` in `Session`, and address presentation operations by ID. Kitty exposes both returned IDs and ID matching in its [remote-control documentation](https://sw.kovidgoyal.net/kitty/remote-control/). Keep a single active controller if that is your preferred UX, but make that the narrow restriction; anchor its keybinding match. If a lock remains necessary, use an actual lock with an appropriate lifetime rather than a PID-file convention.

### 10. P2 — Notes/directives unexpectedly terminate header continuation

**Location:** `kittydemo/engine.py:251–259`; `README.md:150–164`.

The README says a command is what closes the header block. In the implementation, any note or directive also ends the continuation scan. For example:

```sh
#^ Title
#! private reminder
# detail for the audience
pwd
```

produces a header containing only `Title`, then a separate type/run pair for `# detail for the audience`. No command intervened. I confirmed this with a parser probe. A `#@ pause` between continuation lines has the same structural problem.

**Recommendation:** Either retain explicit header-block state across invisible lines and define directive binding there, or document that continuations must be contiguous apart from blank lines. The latter is smaller if this placement is unnecessary. Do not claim the broader rule without implementing and testing it.

### 11. P2 — The documented outside-Kitty invocation lacks a remote-control address

**Location:** `README.md:50–52`; `kittydemo/driver.py:68–71`.

Adding `listen_on` in Kitty's configuration only creates a listening endpoint. An external caller still needs `--to` or `KITTY_LISTEN_ON` identifying it. The wrapper supplies neither explicitly, and an unrelated terminal/scheduler does not automatically inherit Kitty's environment. The documented setup therefore fails for that caller unless the environment was configured separately.

The installed Kitty help confirms the lookup order: explicit address, environment, then controlling terminal. See [remote control via a socket](https://sw.kovidgoyal.net/kitty/remote-control/#remote-control-via-a-socket).

**Recommendation:** Document an invocation setting `KITTY_LISTEN_ON` to the actual configured endpoint, or scope the initial supported workflow to launching inside Kitty. There is no need to add another CLI flag if the existing environment mechanism suffices. Also let `_windows()` distinguish an unreachable Kitty instance from a successful empty listing rather than swallowing the useful error.

### 12. P2 — Long header lines break the following line's alignment

**Location:** `kittydemo/driver.py:283–298`.

The renderer pads short strings to one terminal width but does nothing when text exceeds that width. A 130-column string in a 120-column terminal ends ten columns into the next row; the following header line starts there, and the remaining border/layout is displaced. `len()` also measures characters rather than display columns for tabs, wide characters, and combining marks.

This is inherited from the Bash renderer, but remains relevant with a fixed 120-column recording and arbitrary window sizes. Finding 1 corrected the terminal used for width measurement and captured output; it did not change this padding/wrapping logic.

**Recommendation:** Prefer explicit carriage-return/newline line endings through the correct presentation PTY and test them with SSH. If wrap-based rendering remains necessary, wrap each line into rows and pad the final row. Do not assume one source line fits one terminal row.

## Smaller issues and inconsistencies

- **P3 — Infinite CLI pause is accepted.** `kitty-demo.py:154` rejects negatives and NaN but not positive infinity, despite its error message promising a finite value. `--check --pause inf sample_command_file.sh` succeeds; recording will eventually call `time.sleep(inf)` and fail. Reuse `math.isfinite()`, already used for directive pauses.
- **P3 — Noenter arguments are silently ignored.** `#@ noenter unexpected` parses successfully (`engine.py:240–247`). Require an empty argument, and consider rejecting duplicate pending directives instead of silently accepting/overwriting them.
- **P3 — Platform/dependency requirements are underspecified.** `_terminal_of()` depends on Linux `/proc` and `/dev/pts`, and width lookup uses GNU-style `stty -F`. This is not generally portable just because Kitty and Python are available. `Path.unlink(missing_ok=True)` also establishes a Python 3.8+ requirement. Record mode requires a compatible asciinema; the automatic Niri helper requires `jq`. Document the supported Linux environment and external dependencies, or implement portability deliberately.
- **Resolved P3 — The display hid useful content.** The Finding 4 HUD now wraps notes, budgets surrounding groups against terminal height, provides scrolling for oversized notes, and shows the selected source line. Notes and their items remain grouped during layout and navigation.
- **P3 — Destructive-command highlighting is an unreliable distraction.** `hud.py:26–28` has a word boundary before the entire alternation, so a normal spaced redirect such as `echo x > /dev/sda` does not match its advertised redirect branch. It also flags harmless command text such as `echo rm -rf`. Either remove the heuristic or describe it as an incomplete textual hint. It should not carry the burden of making advancement correct.
- **Partly resolved P3 — Documentation and completion messages overclaim.** The README now states that headers take a press and that final F2 returns to the Controller shell. The recording HUD now says it is finalizing instead of claiming recording has already stopped. New CLI cleanup tests read the actual sample file. The unrelated `pnpm run casts` instruction remains unsupported by this repository and still needs attention.

## Suggested simplification plan

1. **Keep the core interfaces:** executable launcher, positional command-file argument, F1/F2/F3 controls, a pure parser, and a real presentation terminal. Keep `#@ noenter`: immediate TUI keystrokes need an explicit exception to automatic Enter. The clear/header merge is a reasonable convenience if its rules stay narrow.
2. **Use the launch result as session identity.** Add the returned window ID to the existing `Session`; route sends, the outer-window lookup, and teardown through it. Retain the implemented snapshot-based inner-PTY discovery. IDs remove much of the motivation for global title matching, leftover-window rejection, and a home-directory PID file. This does not require supporting multiple simultaneous presenters.
3. **Implemented: request-based input.** Enter-delimited requests now cover advancement, navigation, and viewport scrolling without raw mode or debounce. Ctrl-C/EOF and resize handling are tested with actual PTYs.
4. **Finish the lifecycle around the implemented PTY discovery.** Keep the snapshot approach, move device validation before prompt setup, clean up launch failures, and verify recording completion before publication. Keep configurable pauses and document the accepted startup/command timing assumptions. Direct recorder launch can be considered separately if it simplifies ownership; a shell handshake is not part of the selected plan.
5. **Move personal presentation policy out of the generic launch path.** The 55-pixel margins, Niri monitor placement, forced 120×24 size, Bash-specific prompt mutations, and external cast-processing instructions are personal workflow choices. Put the desktop/prompt setup in a small optional wrapper or documented local configuration. Do not replace them with a large framework of options. In particular, record mode chooses `$SHELL` but then sends Bash-oriented setup; choose a supported recording shell explicitly if that setup stays.
6. **Delete or shrink peripheral features.** The destructive-command regex remains a removal candidate. The directory validator is small and shares the parser, so keeping it is defensible if you actually use it. Retain the agreed full-height command list and readable notes implemented for Finding 4.
7. **Implemented: manual-detour contract.** Manual input remains unconstrained. The README explains retyping or skipping canceled input with F1/F3 and restoring the expected application state before resuming.

There is no need to collapse everything into one large Python file. Separating parsing from terminal side effects already helps testing. Reduce policies and hidden assumptions before reducing the module count.

One product distinction to decide deliberately: the old Bash script automatically recorded live presentations when asciinema was installed. The rewrite couples recording to unattended advancement; normal live mode no longer records. Your stated requirements do not explicitly require recording live Q&A, so I have not classified this as a defect. If that workflow matters, recording and automatic advancement need to be independent concepts.

## Verification and test gaps

The implementation verification command is `python3 -m unittest discover -s tests -t .`. The suite now has **92 tests**: the original 56 parser tests, seven PTY-discovery tests, 22 navigation/playback, HUD, and real-terminal input tests, and seven explicit-key tests. Coverage includes type/run recovery, header navigation, selection-only behavior, completion, unchanged record steps/pauses, full note access, sizing/wrapping, Ctrl-C/EOF cleanup, non-echoing requests, and resize during a partial request. Recorder startup/shutdown gaps remain. `Session` width/output were exercised by the separate real-recording diagnostic, not a committed automated test.

The installed Kitty parser accepted the five documented mappings and confirmed that the navigation/scroll payloads end in actual newlines and only PageUp/PageDown are focus-conditional. An additional full-controller PTY diagnostic, with presentation effects mocked, reached the completion screen and confirmed that Ctrl-C exits 130, releases the session claim, and restores the terminal and alternate screen without a traceback. No user's Kitty configuration or existing Presentation window was modified.

Original diagnostic probes confirmed header/note parsing, lost command indentation, noenter argument acceptance, infinite CLI pause acceptance, EOF behavior, Ctrl-C handling in a PTY, the payload of a pending run action, cleanup failure publication, and missing teardown after launch failure. An isolated real asciinema recording demonstrated the original inner/outer PTY mismatch. After the fix, a second isolated recording confirmed correct inner-PTY selection, 120-column width, and capture of a unique header through `draw_header()`. Installed Kitty help/source and its escape parser were inspected without sending remote-control commands to your windows.

I did not launch or close any of your Kitty windows, execute your demonstration commands, or exercise SSH/sudo/Vim interactively. Full graphical behavior and recorder shutdown timing still need a controlled integration rehearsal; the report distinguishes those unverified timing risks from directly reproduced defects.

The most valuable added checks would be:

- Maintain the new PTY input/navigation tests when extending controls; Ctrl-C/EOF, non-echoing input, resize, and one-Enter advancement are now covered.
- Payload tests preserving whitespace and backslashes through the driver boundary.
- Extend the existing launch-selection tests to verify cleanup after discovery/startup failure, early recorder exit, failed shutdown, and preservation of the previous cast.
- Turn the successful isolated header-recording diagnostic into a repeatable integration test. Separately verify that the CLI waits for finalization before reporting success; the diagnostic finished its recorder normally and did not test the CLI's close-window/rename path.
- Parser cases for invisible lines inside headers and combined directives; use the actual sample file as a fixture if documentation promises that coverage.

These would cover the risky boundaries much more effectively than adding more variations of already-tested type/run sequences.
