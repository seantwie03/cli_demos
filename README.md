# Kitty Demo Controller

This project provides a script to control a Kitty terminal for giving step-by-step command-line demonstrations. It allows a presenter to send pre-written commands from a controller window to a dedicated presentation window.

## How It Works

The system uses Kitty's remote control capabilities (`kitty @`) and two custom keybindings to orchestrate the demo:

1.  **Launch**: Pressing a keyboard shortcut launches a new, dedicated "Controller" window, which immediately starts the `kitty-demo.sh` script.
2.  **Presentation Window**: The script instantly spawns a second, clean "Presentation" window. This window has a large font and margins, making it easy for an audience to read.
3.  **Step-by-Step Execution**: The script reads commands from `sample_command_file.sh`. Each time you press `F1`, the next command or header is processed.
4.  **Headers**: Header lines (starting with `#^`) are displayed as large, formatted blocks in the "Presentation" window.
5.  **Commands**: Command lines are typed into the prompt of the "Presentation" window, ready for you to execute.
6.  **Presenter Notes**: Note lines (starting with `#!`) are displayed only in the "Controller" window, visible only to you.

## Setup

1.  **Edit `kitty.conf`**: Add the following two key mappings to your `kitty.conf` file. You must use the **absolute path** to the `kitty-demo.sh` script.

    ```
    # Launches the Controller window and starts the demo script
    map kitty_mod+n launch --cwd=current --title=Controller sh /path/to/your/kitty-demo/kitty-demo.sh

    # Sends the "next command" signal (Enter) to the Controller window
    map f1 remote_control send-key --match 'title:Controller' enter
    ```

2.  **Prepare Your Commands**: Edit the `sample_command_file.sh` file to include the commands and notes for your demonstration. See the "Command File Syntax" section below.

## How to Use

1.  From any Kitty window, press `kitty_mod+n` (e.g., `Cmd+n` on macOS or `Ctrl+Shift+n` on Linux) to start the demo.
2.  Two new windows will appear: "Controller" and "Presentation". You can arrange these on your screens as needed.
3.  Press `F1` to process the first line of your `sample_command_file.sh`.
    - To use a different command file, modify the CMD_FILE variable at the top
4.  Continue pressing `F1` to send the next header or command.
5.  To **execute** a command that has been typed into the "Presentation" window, you must click on that window and press `Enter` manually.

## Command File Syntax

The command file is a simple text file where each line is processed one by one.

*   **Headers**: Lines starting with `#^` are treated as section headers. The script will display them in a formatted block in the presentation terminal. Any subsequent lines starting with a plain `#` are considered part of that header.
    ```
    #^ This is a main header
    # This is a sub-point for the header
    ```
*   **Presenter Notes**: Lines starting with `#!` are presenter notes. They are echoed only in the "Controller" window for you to see.
    ```
    #! Remind the audience about the next step.
    ```
*   **Commands**: Any other line is treated as a shell command to be typed into the prompt of the "Presentation" window.
    ```
    ls -l
    echo "Hello, World!"
    ```

## Files

*   `kitty-demo.sh`: The main controller script.
*   `sample_command_file.sh`: An example command file.
*   `README.md`: This file.