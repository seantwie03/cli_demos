# Put the full path to your command file here
export CMD_FILE=./sample_command_file.sh
export CURRENT_LINE=
export NEXT_CMD_INDEX=1

function __find_next_cmd() {
    CURRENT_LINE=$(sed -n ${NEXT_CMD_INDEX}p "$CMD_FILE")
    while [[ -z "$CURRENT_LINE" ]] || [[ "$CURRENT_LINE" =~ ^[[:space:]]*$ ]]; do
        ((NEXT_CMD_INDEX++))
        CURRENT_LINE=$(sed -n ${NEXT_CMD_INDEX}p "$CMD_FILE")
        if (($NEXT_CMD_INDEX > 100)); then
            echo "End of demonstration"
            break
        fi
    done
}

function __print_next_cmd() {
    while [[ "$CURRENT_LINE" == \#^* ]]; do
        echo -e "\n########################################################################################################################"
        echo "    ${CURRENT_LINE#\#^}"
        while true; do
            local peek_line_content=$(sed -n $((NEXT_CMD_INDEX + 1))p "$CMD_FILE")
            if [[ "$peek_line_content" == \#* ]] && [[ "$peek_line_content" != \#^* ]]; then
                echo "    ${peek_line_content#\#}"
                ((NEXT_CMD_INDEX++))
            else
                break
            fi
        done
        echo -e "########################################################################################################################\n"
        ((NEXT_CMD_INDEX++))
        __find_next_cmd
    done
    READLINE_LINE="$CURRENT_LINE"
    READLINE_POINT=${#READLINE_LINE}
}

function next_cmd() {
    if [[ ! -e "$CMD_FILE" ]]; then
        echo "No command file. Use CMD_FILE=filename"
        return 9
    fi
    __find_next_cmd
    __print_next_cmd
    ((NEXT_CMD_INDEX++))
}

function prev_cmd() {
    ((NEXT_CMD_INDEX--))
    READLINE_LINE=""
    READLINE_POINT=0
}

function reset_cmd() {
    NEXT_CMD_INDEX=1
    READLINE_LINE=""
    READLINE_POINT=0
}

bind -x '"\C-xn": next_cmd'
bind -x '"\C-xp": prev_cmd'
bind -x '"\C-xr": reset_cmd'

