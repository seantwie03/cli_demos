kitten @ set-font-size 30.0 && clear
#^ Inspect the contents of a file system
# 1. Inspect the current working directory
# 2. Inspect a different directory
# 3. Test TUIs like vim

#^ 1. Inspect the current working directory
#! Be sure to say a pnumonic for each command to help the students remember!
pwd
ls

#^ 2. Inspect a different directory
ls /etc/
clear
cd /etc/
ls
clear

#^ 3. Test TUIs like vim
vim /tmp/abc.sh
#! The next line assumes you have this vim-mapping: inoremap jj <ESC>
i#!/bin/bash
echo "Hello, world!"
jj:wq
chmod a+x /tmp/abc.sh
