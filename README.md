# Command Line Demonstrations with Kitty

Many of us in the IT industry have probably had professors that type very, very slowly. Or worse, professors that make a lot of typos. Those can really throw off a demonstration as the professor has to go into troubleshooting mode to figure out why their command didn't work. This project was created to avoid all these problems.

Simply create a "command file" with all the commands that will be ran during the demonstration. During the demo, use a custom keyboard shortcut to read the command file and put the next command on the prompt as if it was typed in by hand. Explain the command to the audience and hit `enter` to execute it. Repeat until the demonstration is complete.

[![asciicast](https://asciinema.org/a/706500.svg)](https://asciinema.org/a/706500)

To see a sped up demonstration using this tool check my [Asciinema profile](https://asciinema.org/~sean-twie03).

## Setup and Usage

1. Download the [kitty-demo.sh](./kitty-demo.sh) script.
2. Add the following maps to your `kitty.conf`.
    ```kitty.conf
    # Starts the demo script in the current window. Becomes the "Controller" window.
    # Also launches the Presentation window
    map kitty_mod+p launch --cwd=current --title=Controller sh /path/to/kitty-demo.sh

    # Advances the demo by sending an 'enter' keypress to the Controller which triggers
    # the script running inside the controller window to send the next line from 
    # the CMD_FILE to the Presentation window
    map f1 remote_control send-key --match 'title:Controller' enter
    ```
3. Write a [command file](#command-file-syntax) with all the commands that will be ran during the demo.
4. Specify your command file by updating the `CMD_FILE` variable at the top of the [kitty-demo.sh](./kitty-demo.sh) script.
5. Start the demonstration by pressing `kitty_mod+p` (e.g., `Cmd+p` on macOS or `Ctrl+Shift+p` on Linux) in any Kitty window. This will create a "Controller" window where private presenter notes will appear. A new "Presentation" window will also appear. This is where your demo takes place. You can `ssh` to a remote host from this window, if needed.
6. Run the Demonstration by pressing `F1` to process the next line from your command file. This will either display a header or place the next command on the prompt in the Presentation window. The terminal remains fully interactive for any ad-hoc commands.

If you don't want to use the Kitty terminal, checkout the [other implementations](#other-implementations) that have more limitations, but their only requirement is Bash.

## Mechanism

This implementation utilizes [Kitty's remote control](https://sw.kovidgoyal.net/kitty/overview/#remote-control) capability to orchestrate the demonstration across multiple windows.

* The system uses two Kitty windows:
    * The Controller window runs the main `kitty-demo.sh` script, which reads the command file and displays private presenter notes.
    * The Presentation window is where the audience sees the action. The script sends commands and headers to this window.

* The kitty-demo.sh script acts as the central controller. It waits for input and uses `kitty @ send-text` to write commands to the Presentation window's prompt.

* The F1 keybinding simply sends an enter keypress to the Controller window. The read command inside the `kitty-demo.sh` script receives this keypress, which triggers it to process and send the next line from the command file.

## Command File Syntax
The command file is a simple text file where each line is processed one by one. At the top of [kitty-demo.sh](./kitty-demo.sh) is a `CMD_FILE` variable. Modify this variable if you want to specify a different command file.

* **Headers**: Lines starting with `#^` are treated as section headers. The script will display them in a formatted block in the presentation terminal. Any subsequent lines starting with a plain `#` are considered part of that header.
    ```
    #^ This is a header
    # This is part of a more detailed description
    ```
* **Presenter Notes**: Lines starting with `#!` are presenter notes. They are echoed only in the "Controller" window for you to see.
    ```
    #! Give the audience a pnumonic for each command, flag and argument!
    ```
* **Commands**: Any other line is treated as a shell command to be typed into the prompt of the "Presentation" window.
    ```
    ls -l
    echo "Hello, World!"
    ```

**Example**: [sample_command_file.sh](./sample_command_file.sh)

## Thanks

Thanks to [Kovid Goyal](https://sw.kovidgoyal.net/kitty/support/) for making such an awesome terminal program!

## Other Implementations

This repo has three branches. Each branch uses different technology to accomplish the stated goal above.

### Readline

**Branch**: [readline](https://github.com/seantwie03/cli_demos/tree/readline?tab=readme-ov-file)

**Complexity**: Low

#### Details

Uses Bash functions to manipulte `readline`. Very simple implementation.

This implementation does not work when escalating to `root` or switching users. Does not work in Text User Interfaces (TUIs) like `vim` or `parted`.

### Readline Multi-User

**Branch**: [readline-multi-user](https://github.com/seantwie03/cli_demos/tree/readline-multi-user?tab=readme-ov-file)

**Complexity**: Moderate

#### Details

Similar to `readline` but accessible to every user on the system. The keyboard shorcut will continue to work when escalating to `root` or switching users.

Does not work in TUIs like `vim` or `parted`.

### Main

**Branch**: [main](https://github.com/seantwie03/cli_demos)

**Complexity**: High

#### Details

A more complicated solution that utilizes Kitty's remote control capability. This implementation allows usage of the presenter notes. It works when escalating to `root` and switching users. It also works in TUIs like `vim` and `parted`. Requires the [Kitty](https://sw.kovidgoyal.net/kitty/) Terminal which only runs on Mac, Linux, and [WSLg](https://learn.microsoft.com/en-us/windows/wsl/tutorials/gui-apps).

