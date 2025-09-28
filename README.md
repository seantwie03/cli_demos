# Command Line Demonstrations with Kitty

Many of us in the IT industry have probably had professors that type very, very slowly. So slowly that you feel like you might fall asleep watching them type. Or worse, professors that make a lot of typos. Those can really throw off a demonstration as the professor has to go into troubleshooting mode to figure out why their command didn't work. This project was created to avoid all these problems.

First create a "command file" with all the commands that will be ran during the demonstration. During the demo, use a custom keyboard shortcut to read the command file and put the next command on the prompt as if it was typed in by hand. Explain the command to the audience and hit `enter` to execute it. Repeat until the demonstration is complete.

## How It Works

This project manipulates Bash's [READLINE_LINE](https://www.gnu.org/software/bash/manual/html_node/Bash-Variables.html#index-READLINE_005fLINE) and [READLINE_POINT](https://www.gnu.org/software/bash/manual/html_node/Bash-Variables.html#index-READLINE_005fPOINT) variables using `bind -x` keybindings.

The system uses a "command file" and three Bash keybindings to orchestrate the demonstration.

The [command file](#command-file-syntax) is a list of shell commands that will be ran as part of the demo. You can optionally include section headers and descriptive comments.

1. The first keybinding is for the `next_cmd` function. Pressing this keybinding puts the next line from the command file on your prompt. If the next line is a section header, it echoes it instead.

```sh
bind -x '"\C-xn": next_cmd'
```

2. The second keybinding is for the `prev_cmd` function. If you need to go back to a previous line, you can use this keybinding.

```sh
bind -x '"\C-xp": prev_cmd'
```

3. The third keybinding is the `reset_cmd` function. Use this keybinding in between demonstrations to reset back to line one.

```sh
bind -x '"\C-xr": reset_cmd'
```

All of the functions and environment variables that make this work is in [demonstration_functions.sh](./demonstration_functions.sh).

## Limitations

This implementation very simple; just a few lines of Bash code with no dependencies. This simplicity limits the capabilities. This implementation does not support escalating to `root` or switching users. Nor does it support Text User Interfaces (TUIs) like `vim` or `parted`. If a command in the command file does either of these, you'll have to type that section of the demonstartion manually. After you exit back to the primary demonstration shell (quitting vim for example), you can resume using the `next_cmd` keybinding. 

To see more complex impelentations that do not have these weaknesses check the [other branches in this repo](#other-implementations).

## How to Use

1. Download the `demonstration_functions.sh` file to a location that is readable by whichever user will be used to do the demonstration. (Escalating to `root` or switching users is not supported.)
1. Source the `demonstration_functions.sh` script manually or in your `.bashrc`.
1. Set the `CMD_FILE` variable to the full path of your command file. This can be done by editing the `CMD_FILE` variable in demonstration_functions.sh script or by running a command like `export CMD_FILE=/path/to/command/file.sh`.
1. Press the `<C-x>n` (Hold `Control`, Press `x`, Release `Control`, Press `n`). The first section header will appear in your terminal or the first command will appear on your prompt.
1. Continue pressing `<C-x>n` to send the remaining lines from the command file.

## Command File Syntax
The command file is a simple text file where each line is processed one by one. At the top of [demonstration_functions.sh](./demonstration_functions.sh) is a `CMD_FILE` variable. Modify this variable if you want to specify a different command file.

*   **Headers**: Lines starting with `#^` are treated as section headers. The script will display them in a formatted block in the presentation terminal. Any subsequent lines starting with a plain `#` are considered part of that header.
    ```
    #^ This is a header
    # This is part of a more detailed description
    ```
*   **Commands**: Any other line is treated as a shell command to be typed into the prompt of the "Presentation" window.
    ```
    ls -l
    echo "Hello, World!"
    ```

**Example**: [sample_command_file.sh](./sample_command_file.sh)

## Files

*   `demonstration_functions.sh`: The file to import into your bashrc.
*   `sample_command_file.sh`: An example command file.
*   `README.md`: This file.

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

