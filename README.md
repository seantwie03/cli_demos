# Command Line Demonstrations with Kitty

Many of us in the IT industry have probably had professors that type very, very slowly. So slowly that you feel like you might fall asleep watching them type. Or worse, professors that make a lot of typos. Those can really throw off a demonstration as the professor has to go into troubleshooting mode to figure out why their command didn't work. This project was created to avoid all these problems.

First create a "command file" with all the commands that will be ran during the demonstration. During the demo, use a custom keyboard shortcut to read the command file and put the next command on the prompt as if it was typed in by hand. Explain the command to the audience and hit `enter` to execute it. Repeat until the demonstration is complete.

To see a sped up version of a demonstration using this tool check my [Asciinema profile](https://asciinema.org/~sean-twie03)

## Setup and Usage

1. Write a [command file](#command-file-syntax) with all the commands that will be ran during the demo.
2. Source the `demonstration_function.sh` script:
    ```sh
    source /path/to/demonstration_functions.sh
    ```
3. Set the `CMD_FILE` environement varaible to the absolute path of your command file:
    ```sh
    export CMD_FILE=/path/to/your/command/file.sh
    ```
4. Use the following keybinding to control the demonstration:
    * `Ctrl-x n` (`next_cmd`): Places the next command or displays the next header.
    * `Ctrl-x p` (`prev_cmd`): Moves back to the previous command.
    * `Ctrl-x r` (`reset_cmd`): Resets the demonstration to the beginning of the file.

All of the functions and environment variables that make this work is in [demonstration_functions.sh](./demonstration_functions.sh).

## Limitations

This implementation very simple; just a few lines of Bash code with no dependencies. This simplicity limits the capabilities. This implementation does not support escalating to `root` or switching users. Nor does it support Text User Interfaces (TUIs) like `vim` or `parted`. If a command in the command file does either of these, you'll have to type that section of the demonstartion manually. After you exit back to the primary demonstration shell (quitting vim for example), you can resume using the `next_cmd` keybinding. 

To see more complex impelentations that do not have these weaknesses check the [other branches in this repo](#other-implementations).

## Mechanism

This script uses `bind -x` command to map key sequences to Bash functions. These functions manipulate the [READLINE_LINE](https://www.gnu.org/software/bash/manual/html_node/Bash-Variables.html#index-READLINE_005fLINE) and [READLINE_POINT](https://www.gnu.org/software/bash/manual/html_node/Bash-Variables.html#index-READLINE_005fPOINT) variables to programmatically populate the command prompt.

## Command File Syntax
The command file is a simple text file where each line is processed one by one. At the top of [demonstration_functions.sh](./demonstration_functions.sh) is a `CMD_FILE` variable. Modify this variable if you want to specify a different command file.

* **Headers**: Lines starting with `#^` are treated as section headers. The script will display them in a formatted block in the presentation terminal. Any subsequent lines starting with a plain `#` are considered part of that header.
    ```
    #^ This is a header
    # This is part of a more detailed description
    ```
* **Commands**: Any other line is treated as a shell command to be typed into the prompt of the "Presentation" window.
    ```
    ls -l
    echo "Hello, World!"
    ```

**Example**: [sample_command_file.sh](./sample_command_file.sh)

## Other Implementations

This repo has three branches. Each branch uses different technology to accomplish the stated goal above.

### Readline

**Branch**: [readline](https://github.com/seantwie03/cli_demos/tree/readline?tab=readme-ov-file)

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

