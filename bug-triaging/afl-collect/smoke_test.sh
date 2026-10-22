#!/bin/bash
# The triager can run: afl-collect starts and gdb loads its exploitable plugin.
set -e
afl-collect --help > /dev/null
P=$(python3 -c "import exploitable, os; print(os.path.join(exploitable.__path__[0], 'exploitable.py'))")
gdb -nx -batch -ex "source $P" -ex "help exploitable" | grep -qi exploitable
echo "afl-collect triager OK"
