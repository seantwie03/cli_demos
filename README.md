# Command Line Demonstrations with Kitty

Many of us in the IT industry have probably had professors that type very, very slowly. So slowly that you feel like you might fall asleep watching them type. Or worse, professors that make a lot of typos. Those can really throw off a demonstration as the professor has to go into troubleshooting mode to figure out why their command didn't work. This project was created to avoid all these problems.

First create a "command file" with all the commands that will be ran during the demonstration. During the demo, use a custom keyboard shortcut to read the command file and put the next command on the prompt as if it was typed in by hand. Explain the command to the audience and hit `enter` to execute it. Repeat until the demonstration is complete.

## How It Works

This project utilizes [Kitty's remote control](https://sw.kovidgoyal.net/kitty/overview/#remote-control) capability to make command line demonstrations effortless. It accomplishes this by allowing a presenter to send pre-written commands from a "Controller" Kitty window to a "Presentation" Kitty window.

The system uses a "command file" and two custom Kitty keybinds to orchestrate the demonstration.

The [command file](#command-file-syntax) is a list of shell commands that will be ran as part of the demo. You can optionally include section headers, descriptive comments, and presenter notes.

The first Kitty keybinding launches the script. The window you are in when you press this keybinding is where the presenter notes will show.

```~/.config/kitty/kitty.conf
# Launches the Controller window and starts the demo script
map kitty_mod+p launch --cwd=current --title=Controller sh /path/to/your/kitty-demo/kitty-demo.sh
```

The second Kitty keybinding sends the `enter` key to the window running the script. This prompts the script to send the next line of output to the Presentation window. Press this keybinding from any window to advance the presentation.

```~/.config/kitty/kitty.conf
# Sends the "next command" signal (enter) to the Controller window
map f1 remote_control send-key --match 'title:Controller' enter
```

Add these keybindings to your [Kitty config](https://sw.kovidgoyal.net/kitty/conf/).

## How to Use

1.  From any Kitty window, press `kitty_mod+p` (e.g., `Cmd+p` on macOS or `Ctrl+Shift+p` on Linux) to start the demo. Your current window will become the "Controller" window.
2.  A new "Presentation" window will appear. This is where the section headers, comments, and commands will be sent.
    - If your demonstration will take place on a remote server, you can `ssh` into that server in the Presentation window. This can be accomplished by typing the `ssh` command by hand or having it as the first line in your command file.
3.  Press `F1` to process the first line of your `sample_command_file.sh`.
    - This will print the first section header or put the first command on your prompt. Explain the command to your audience and hit `enter` to execute it.
    - If your audience asks a question, the terminal is available to type any additional "adhoc" commands as needed.
    - To use a different command file, modify the `CMD_FILE` variable at the top of `kitty-demo.sh`.
4.  Continue pressing `F1` to send the remaining lines from the command file.

## Command File Syntax
The command file is a simple text file where each line is processed one by one. At the top of [kitty-demo.sh](./kitty-demo.sh) is a `CMD_FILE` variable. Modify this variable if you want to specify a different command file.

*   **Headers**: Lines starting with `#^` are treated as section headers. The script will display them in a formatted block in the presentation terminal. Any subsequent lines starting with a plain `#` are considered part of that header.
    ```
    #^ This is a header
    # This is part of a more detailed description
    ```
*   **Presenter Notes**: Lines starting with `#!` are presenter notes. They are echoed only in the "Controller" window for you to see.
    ```
    #! Give the audience a pnumonic for each command, flag and argument!
    ```
*   **Commands**: Any other line is treated as a shell command to be typed into the prompt of the "Presentation" window.
    ```
    ls -l
    echo "Hello, World!"
    ```

**Example**: [sample_command_file.sh](./sample_command_file.sh)

## Files

*   `kitty-demo.sh`: The main controller script.
*   `sample_command_file.sh`: An example command file.
*   `README.md`: This file.

## Thanks

Thanks to [Kovid Goyal](https://sw.kovidgoyal.net/kitty/support/) for making such an awesome terminal program!

## Other Implementations

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

Does not work in TUIs like `vim` or `parted`.

### Main

**Branch**: [main](https://github.com/seantwie03/cli_demos)

**Complexity**: High

#### Details

A more complicated solution that utilizes Kitty's remote control capability. This implementation allows usage of the presenter notes. It works when escalating to `root` and switching users. It also works in TUIs like `vim` and `parted`. Requires the [Kitty](https://sw.kovidgoyal.net/kitty/) Terminal which only runs on Mac, Linux, and [WSLg](https://learn.microsoft.com/en-us/windows/wsl/tutorials/gui-apps).

