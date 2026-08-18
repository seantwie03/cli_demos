#!/bin/bash

CMD_FILE='/home/sean/s/cli_demos/./sample_command_file.sh'

if [ ! -f "$CMD_FILE" ]; then
  echo "Error: Command file not found at: $CMD_FILE" >&2
  # Keep the window open for a bit so the user can see the error.
  sleep 10
  exit 1
fi

# I couldn't get sending carriage return and new line characters to work when
# SSH'd into another machine. So... I came up with this hack.
# It calculates the amount of blank space available after the line content from
# the CMD_FILE. Then it puts that many space characters. This way the next line
# from the CMD_FILE will be printed starting at column 1 on the next line down.
# Color for the Section Headers (borders and text alike).
COLOR_RESET=$'\033[0m'
HEADER_COLOR=$'\033[1;34m'

# This function is only intended to be used for Section Headers.
# The optional second argument is an ANSI color escape applied to the text.
# The padding is calculated from the plain text, so the escape codes (which
# take up no columns on screen) don't throw off the line wrapping.
print_line_and_wrap() {
  local text="$1"
  local color="${2-}"
  # Print the text without a newline
  printf "%s%s%s" "$color" "$text" "${color:+$COLOR_RESET}" > "$PRESENTATION_TTY"
  # Calculate spaces needed to fill the line
  local spaces_to_fill=$((width - ${#text}))
  # Print the spaces if needed
  if (( spaces_to_fill > 0 )); then
    printf "%*s" "$spaces_to_fill" "" > "$PRESENTATION_TTY"
  fi
}

# --- Main Script Logic ---

echo "Starting Kitty Demo Controller..."
echo "Command file: $CMD_FILE"

# I want section headers to be big and colorful. I want them to appear in the
# terminal without having to echo them. When doing that, the echo command I
# execute ends up taking as much space as the printed out header and it is
# ugly. So... another hack. 
# First I capture all the pseudo terminals (/dev/pts/*).
# Then I spawn the Presentation terminal. 
# Then I capture all the pseudo terminals again. I assume the new pts device
# is the Presentation terminal.
# Now that I know which pts device is the Presentation terminal, I can input
# text directly to the terminal. This makes Section Headers look good!

# 1. Capture existing TTYs
echo "Capturing initial TTY devices..."
ttys_before=$(ls /dev/pts/* 2>/dev/null)

# 2. Spawn Presentation window
echo "Spawning new 'Presentation' window..."
kitten @ launch --type=os-window --title="Presentation" --spacing='margin=55'
if [[ "$XDG_CURRENT_DESKTOP" == "niri" ]]; then
    sleep 1
    PRES_WIN_ID=$(niri msg --json windows | jq -r '.[] | select(.title == "Presentation") | .id')
    "$(dirname "$0")/niri-maximize_on_other_monitor.sh" "$PRES_WIN_ID"
fi
if command -v asciinema >/dev/null 2>&1 ; then
    #kitty @ send-text --match 'title:^Presentation$' -- "asciinema rec /tmp/$(basename ${CMD_FILE%.*}.cast) --overwrite --window-size 120x25"
    kitty @ send-text --match 'title:^Presentation$' -- "asciinema rec /tmp/$(basename ${CMD_FILE%.*}.cast) --overwrite"
    kitty @ send-key --match 'title:^Presentation$' enter
fi

# 3. Wait and find the new TTY
sleep 0.5
ttys_after=$(ls /dev/pts/* 2>/dev/null)

PRESENTATION_TTY=$(comm -13 <(echo "$ttys_before") <(echo "$ttys_after") | tail -n1)

if [ -z "$PRESENTATION_TTY" ]; then
  echo "Error: Could not determine TTY for the 'Presentation' window." >&2
  echo "Please ensure you are running in a graphical environment." >&2
  sleep 10
  exit 1
fi

echo "Presentation window created on TTY: $PRESENTATION_TTY"
echo "You can now use your 'Next Command' key (e.g., F1) to advance the demo."

# 4. Read the command file into an array.
mapfile -t lines < <(grep -v -e '^$' "$CMD_FILE")

preview_next_command() {
  if (( i < ${#lines[@]} )); then
    local next_line="${lines[i]}"
    local trimmed_next="${next_line#"${next_line%%[![:space:]]*}"}"

    if [[ "$trimmed_next" == '#!'* ]]; then
      echo "Next: [Speaker Note]"
    else
      echo "Next: $next_line"
    fi
  else
    echo "Next: (End of script)"
  fi
}

# 5. Loop through the commands, waiting for user input each time.
i=0
preview_next_command
while (( i < ${#lines[@]} )); do
  # Wait for the 'Next Command' keybinding to send an Enter keystroke to this script.
  read

  cmd="${lines[i]}"
  # Trim leading whitespace to make parsing resilient
  trimmed_cmd="${cmd#"${cmd%%[![:space:]]*}"}"

  if [[ "$trimmed_cmd" == '#!'* ]]; then
    # Presenter note: echo to this terminal and move to the next command immediately.
    echo "Note: ${trimmed_cmd#\#!}"
    ((i++))
    preview_next_command
    continue
  fi

  if [[ "$trimmed_cmd" == '#^'* ]]; then
    # Header block starts.
    # Using spaces to force line wraps, since I couldn't get '\n' to work
    # Get the terminal width (columns) from stty.
    width=$(stty -F "$PRESENTATION_TTY" size 2>/dev/null | cut -d' ' -f2)
    # Fallback to 120 if stty fails.
    : ${width:=120}

    # Move cursor to the line below the prompt
    printf '\r' > "$PRESENTATION_TTY"

    border_line=$(printf '#%.0s' $(seq 1 $width)) # Display a full line of #s

    # Blank line to separate the header from whatever is above it
    print_line_and_wrap ""

    # Print content using the helper function
    print_line_and_wrap "$border_line" "$HEADER_COLOR"

    # Main header
    main_header_text="    ${trimmed_cmd#\#^ }"
    print_line_and_wrap "$main_header_text" "$HEADER_COLOR"
    ((i++))

    # Subsequent lines
    while (( i < ${#lines[@]} )); do
      line="${lines[i]}"
      # Trim leading whitespace to make parsing more resilient
      trimmed_line="${line#"${line%%[![:space:]]*}"}"

      if [[ "$trimmed_line" == '#'* && "$trimmed_line" != '#^'* && "$trimmed_line" != '#!'* ]]; then
        sub_line_text="        ${trimmed_line#\# }"
        print_line_and_wrap "$sub_line_text" "$HEADER_COLOR"
        ((i++))
      else
        break
      fi
    done

    print_line_and_wrap "$border_line" "$HEADER_COLOR"

    # Send an ENTER key to make the prompt reappear below the section header
    kitty @ send-key --match 'title:^Presentation$' enter

    preview_next_command
    continue
  fi

  # This is a regular command to be typed at the prompt in the presentation window.
  kitty @ send-text --match 'title:^Presentation$' -- "$cmd"
  ((i++))
  preview_next_command
done

# Print a final message to the controller window
echo "All commands sent. Demo finished."

sleep 3

# Type "End of Demonstration" into the presentation window's prompt
kitty @ send-text --match 'title:^Presentation$' -- "# End of Demonstration"

# Display the Demo finished message for several seconds before closing.
sleep 5
