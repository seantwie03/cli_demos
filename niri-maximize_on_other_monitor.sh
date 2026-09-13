#!/bin/bash
# Move an identified window to a chosen output, then maximize its column.
# Usage: niri-maximize_on_other_monitor.sh [window-id] [output]
# Without arguments, use the focused window and next output by connector name.
set -euo pipefail
DESKTOP=${XDG_CURRENT_DESKTOP:-}
[[ ":${DESKTOP,,}:" == *:niri:* ]] || exit 0
WINDOW_ID=${1:-$(niri msg --json windows | jq -er '.[] | select(.is_focused) | .id')}
TARGET_OUTPUT=${2:-}
if [[ -z "$TARGET_OUTPUT" ]]; then
    SOURCE_OUTPUT=$(niri msg --json workspaces | jq -r '.[] | select(.is_focused) | .output')
    TARGET_OUTPUT=$(niri msg --json outputs | jq -er --arg source "$SOURCE_OUTPUT" '
        [to_entries[] | select(.value.current_mode != null) | .key] | sort |
        if length == 0 then error("no active outputs")
        else .[((index($source) // -1) + 1) % length] end')
fi
niri msg action move-window-to-monitor --id "$WINDOW_ID" "$TARGET_OUTPUT"
# Niri exposes maximize-column only for the focused column. Explicitly focus
# the owned window first instead of maximizing whichever window launch focused.
niri msg action focus-window --id "$WINDOW_ID"
niri msg --json windows | jq -e --argjson id "$WINDOW_ID" '.[] | select(.id == $id and .is_focused)' >/dev/null
niri msg action maximize-column
