# Command Line Demonstrations with Kitty

Many of us in the IT industry have probably had professors that type very slow. You feel like you might fall asleep watching them type. Or worse, professors that make a lot of typos. That can really throw off a demonstration as the professor has to go into troubleshooting mode to figure out why their command didn't work. This project was created to avoid all these problems.

First create a "command file" with all the commands that will be ran during the demonstration. During the demo, use a custom keyboard shortcut to read the command file and put the next command on the prompt as if I typed it by hand. Then explain the command to the audience and hit Enter to execute it. Repeat until the demonstration is complete.

## Implementations

This repo has three branches. Each branch uses different technology to accomplish the stated goal above.

### Readline

**Branch**: `readline`

**Complexity**: Low

#### Details

Uses Bash functions to manipulte `readline`. Very simple implementation.

This implementation does not work when escalating to `root` or switching users. Does not work in Text User Interfaces (TUIs) like `vim` or `parted`.

### Readline Multi-User

**Branch**: `readline-multi-user`

**Complexity**: Moderate

#### Details

Similar to `readline` but accessible to every user on the system. The keyboard shorcut will continue to work when escalating to `root` or switching users.

Does not work in Text User Interfaces (TUIs) like `vim` or `parted`.

### Main

**Branch**: [main](https://github.com/seantwie03/cli_demos)

**Complexity**: High

#### Details

A more complicated solution that utilizes Kitty's remote control capability. This implementation allows usage of "Speaker Notes." It works when escalating to `root` and switching users. It also works in TUIs like `vim` and `parted`. Requires the [Kitty](https://sw.kovidgoyal.net/kitty/) Terminal which only runs on Mac and Linux (or WSLg).

## How the `main` Branch Works

This project utilizes [Kitty's remote control](https://sw.kovidgoyal.net/kitty/overview/#remote-control) capability to make command line demonstrations effortless. It accomplishes this by allowing a presenter to send pre-written commands from a "Controller" Kitty window to a "Presentation" Kitty window.

The system uses a "command file" and two custom Kitty keybinds to orchestrate the demonstration.

The command file is a essentially a list of shell commands that will be ran as part of the demo. You can optionally include Sections, Presenter Notes, and additional comments.

The first Kitty keybinding launches the script. You press this in the window you want your Presenter notes to show in.

```~/.config/kitty/kitty.conf
# Launches the Controller window and starts the demo script
map kitty_mod+n launch --cwd=current --title=Controller sh /path/to/your/kitty-demo/kitty-demo.sh
```

The second Kitty keybinding sends the Enter key to the window running the script. This prompts the script to send the next line of output to the Presentation window. You press this from the Presentation window to advance the demonstration.

```~/.config/kitty/kitty.conf
# Sends the "next command" signal (Enter) to the Controller window
map f1 remote_control send-key --match 'title:Controller' enter
```

Add these keybindings to your [Kitty config](https://sw.kovidgoyal.net/kitty/conf/).

## How to Use

1.  From any Kitty window, press `kitty_mod+n` (e.g., `Cmd+n` on macOS or `Ctrl+Shift+n` on Linux) to start the demo. Your current window will become the "Controller" window.
2.  A new window will appear. This is the "Presentation" window.
3.  Press `F1` to process the first line of your `sample_command_file.sh`.
    - This will put the command on your prompt. You can then explain the command to your audience and hit [Enter] to execute it.
    - To use a different command file, modify the `CMD_FILE` variable at the top of `kitty-demo.sh`.
4.  Continue pressing `F1` to send the next header or command.

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

## Thanks

Thanks to [Kovid Goyal](https://sw.kovidgoyal.net/kitty/support/) for making such an awesome terminal program!
