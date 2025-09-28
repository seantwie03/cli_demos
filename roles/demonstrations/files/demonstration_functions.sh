# Exit if non-interactive
[[ $- != *i* ]] && return

function __get_state_file() {
    local cmd_file=$(basename "$CMD_FILE")
    local state_file="/tmp/${cmd_file%.*}_state"
    if [[ ! -f "$state_file" ]]; then
        echo '1' > "$state_file"
    fi
    echo "$state_file"
}

function __get_next_cmd_index() {
    local state_file=$(__get_state_file)
    cat "$state_file"
}

function __set_next_cmd_index() {
    local state_file=$(__get_state_file)
    echo "$1" > "$state_file"
    chmod 666 "$state_file" 2>/dev/null || true
}

function __find_next_cmd() {
    local TOTAL_CMDS=$(wc -l <"$CMD_FILE")
    local NEXT_CMD_INDEX=$(__get_next_cmd_index)
    local CURRENT_LINE=$(sed -n ${NEXT_CMD_INDEX}p "$CMD_FILE")

    while [[ -z "$CURRENT_LINE" ]] || [[ "$CURRENT_LINE" =~ ^[[:space:]]*$ ]]; do
        ((NEXT_CMD_INDEX++))
        CURRENT_LINE=$(sed -n ${NEXT_CMD_INDEX}p "$CMD_FILE")
        if (( NEXT_CMD_INDEX > TOTAL_CMDS )); then
            echo "# End of demonstration"
            break
        fi
    done

    __set_next_cmd_index "$NEXT_CMD_INDEX"
    echo "$CURRENT_LINE"
}

function __print_next_cmd() {
    local CURRENT_LINE=$(__find_next_cmd)
    local NEXT_CMD_INDEX=$(__get_next_cmd_index)

    while [[ "$CURRENT_LINE" == \#* ]]; do
        if [[ "$CURRENT_LINE" == '# End of demonstration' ]]; then
            echo "$CURRENT_LINE"
            return
        fi
        if [[ "$CURRENT_LINE" == \#^* ]]; then
            echo -e "\n\033[34m#######################################################################################################################"
            echo -e "   ${CURRENT_LINE#\#^}"
            echo -e "#######################################################################################################################\033[30m"
        else
            echo -e "\033[34m${CURRENT_LINE}\033[30m"
        fi
        ((NEXT_CMD_INDEX++))
        __set_next_cmd_index "$NEXT_CMD_INDEX"
        CURRENT_LINE=$(__find_next_cmd)
    done
    READLINE_LINE="$CURRENT_LINE"
    READLINE_POINT=${#READLINE_LINE}

    # Advance to next command for subsequent call
    local NEXT_CMD_INDEX=$(__get_next_cmd_index)
    ((NEXT_CMD_INDEX++))
    __set_next_cmd_index "$NEXT_CMD_INDEX"
}


function next_cmd() {
    if ! source '/etc/demonstrations/config'; then
        echo "No config file found"
        return 9
    fi
    # /etc/demonstrations/config should contain CMD_FILE variable
    # CMD_FILE variable should point to a file that exists
    if [[ ! -f "$CMD_FILE" ]]; then
        echo "No command file found at $CMD_FILE."
        return 9
    fi
    __print_next_cmd
}

function prev_cmd() {
    local NEXT_CMD_INDEX=$(__get_next_cmd_index)
    if (( NEXT_CMD_INDEX > 1 )); then
        ((NEXT_CMD_INDEX--))
        __set_next_cmd_index "$NEXT_CMD_INDEX"
    fi
    READLINE_LINE=""
    READLINE_POINT=0
}

function reset_cmd() {
    __set_next_cmd_index "1"
    READLINE_LINE=""
    READLINE_POINT=0
}

bind -x '"\C-xn": next_cmd'
bind -x '"\C-xp": prev_cmd'
bind -x '"\C-xr": reset_cmd'
