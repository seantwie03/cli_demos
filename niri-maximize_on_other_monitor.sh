#!/bin/bash
# Moves a window to the other monitor and maximizes it.
# Usage: niri-maximize_on_other_monitor.sh [window-id]
# If window-id is not provided, operates on the focused window.
# Does nothing if not running under niri or only one monitor is connected.
# Dependencies: jq

[[ "$XDG_CURRENT_DESKTOP" == "niri" ]] || exit 0

OTHER_OUTPUT=$(niri msg --json workspaces | jq -r '
    (map(select(.is_focused))[0].output) as $cur |
    map(select(.output != $cur))[0].output
')

if [[ -n "$1" ]]; then
    ID_ARG="--id $1"
fi

if [[ -n "$OTHER_OUTPUT" && "$OTHER_OUTPUT" != "null" ]]; then
    niri msg action move-window-to-monitor $ID_ARG "$OTHER_OUTPUT"
fi
niri msg action maximize-column
