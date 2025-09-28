# Command Line Demonstrations in Bash

Many of us in the IT industry have probably had professors that type very, very slowly. Or worse, professors that make a lot of typos. Those can really throw off a demonstration as the professor has to go into troubleshooting mode to figure out why their command didn't work. This project was created to avoid all these problems.

Simply create a "command file" with all the commands that will be ran during the demonstration. During the demo, use a custom keyboard shortcut to read the command file and put the next command on the prompt as if it was typed in by hand. Explain the command to the audience and hit `enter` to execute it. Repeat until the demonstration is complete.

[![asciicast](https://asciinema.org/a/706500.svg)](https://asciinema.org/a/706500)

To see a sped up demonstration using this tool check my [Asciinema profile](https://asciinema.org/~sean-twie03).

## Setup and Usage

This implementation is designed to be deployed system-wide, making it available to all users. An Ansible playbook is provided to automate the installation.

1.  **Run the Ansible Playbook**: Execute the `initial_setup.yml` playbook to deploy the necessary files.
    ```sh
    ansible-playbook initial_setup.yml
    ```
    The playbook places files in the following locations:
    *   `/etc/profile.d/demonstration_functions.sh`: Sourced on login for all users.
    *   `/etc/demonstrations/config`: Main configuration file where the command file location is specified.
    *   `/opt/demonstrations/sample_command_file.sh`: The command file.

2.  **Log Out and Log In**: For the system-wide profile changes in `/etc/profile.d/` to take effect, you must log out and log back in.

3.  **Set Command File**: To use a command file, edit `/etc/demonstrations/config` and set the `CMD_FILE` variable to the absolute path of your file. For example:
    ```ini
    # /etc/demonstrations/config
    CMD_FILE="/opt/demonstrations/sample_command_file.sh"
    ```

4.  **Control the Demonstration**: Use the following keybindings to control the demonstration:
    *   `Ctrl-x n` (`next_cmd`): Places the next command or displays the next header.
    *   `Ctrl-x p` (`prev_cmd`): Moves back to the previous command.
    *   `Ctrl-x r` (`reset_cmd`): Resets the demonstration to the beginning of the file.

## Mechanism

This script's functionality is built on several core components to allow for system-wide, multi-user demonstrations.

*   **System-Wide Script**: The main script is located at `/etc/profile.d/demonstration_functions.sh`, ensuring it is automatically sourced by all user shells upon login.

*   **Centralized Configuration**: The path to the active command file is read from `/etc/demonstrations/config`. The `next_cmd` function sources this file each time it is run to know which command file to use.

*   **File-Based State Management**: To persist the demonstration's state across different user sessions (e.g., when using `su` or `sudo`), the script stores the current line number in a world-writable file in `/tmp`. The state file's name is derived from the command file's name (e.g., `/tmp/sample_command_file_state`). Because the state is in a globally accessible file, any user's shell can read and modify it.

*   **Bash Keybindings & Readline**: The script uses `bind -x` to map key sequences (`Ctrl-x n`, etc.) to Bash functions. These functions manipulate the [READLINE_LINE](https://www.gnu.org/software/bash/manual/html_node/Bash-Variables.html#index-READLINE_005fLINE) and [READLINE_POINT](https://www.gnu.org/software/bash/manual/html_node/Bash-Variables.html#index-READLINE_005fPOINT) variables to programmatically write commands into the user's prompt.

## Limitations

While this implementation is robust enough to handle multiple users and privilege escalation, it has one main limitation inherent to its design:

*   **Text User Interfaces (TUIs)**: The keybindings (`Ctrl-x n`, etc.) are configured within Bash. When you run a full-screen Text User Interface like `vim` or `parted`, that application takes full control of keyboard input. It interprets all key presses for its own purposes, so the keybindings are never passed back to the parent Bash shell to be processed. You must exit the TUI to resume using the demonstration keybindings.

To see more complex implementations with fewer limitations check the [other branches in this repo](#other-implementations).

## Command File Syntax

The script uses the CMD_FILE environment variable to find your command file. While you can set a default path inside demonstration_functions.sh, it is recommended to set it using export as shown in the setup instructions.

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

**Example**: [sample_command_file.sh](./roles/demonstrations/files/sample_command_file.sh)

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

