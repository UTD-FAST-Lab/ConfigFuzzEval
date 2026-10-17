#!/bin/bash
# Runs SuperC on a benchmark's source files, in parallel, one JVM per file.
#
# Mounted by common/superc.py:
#   the benchmark's source tree, read-only, at its path in the coverage build
#   /out/files.txt      the source files to analyse, as absolute paths (one per line)
#   /out/flags.txt      build flags, one per line: "-I <absolute dir>" or "-D NAME[=VALUE]"
# Writes, for every file /a/b.c:
#   /out/pc/a/b.c.json  its presence-condition tree (SuperC -sourcelinePC)
#   /out/logs/a/b.c.log SuperC's output
# and /out/status.tsv: file, exit code (124 = timed out), seconds.
#
# Environment: SUPERC_JOBS (files at a time, default 1), SUPERC_TIMEOUT (seconds per
# file, default 600), SUPERC_HEAP (JVM heap per file, default 2g).

set -u
JOBS=${SUPERC_JOBS:-1}
TIMEOUT=${SUPERC_TIMEOUT:-600}
HEAP=${SUPERC_HEAP:-2g}
export TIMEOUT HEAP

FLAGS=()
while read -r option value; do
    case "$option" in
        -I|-D) [ -n "$value" ] && FLAGS+=("$option" "$value") ;;
    esac
done < /out/flags.txt
export FLAG_ARGS="${FLAGS[*]}"

: > /out/status.tsv
analyse() {
    file=$1
    out="/out/pc${file}.json"
    log="/out/logs${file}.log"
    mkdir -p "$(dirname "$out")" "$(dirname "$log")"
    start=$(date +%s)
    # shellcheck disable=SC2086
    (cd "$(dirname "$file")" && timeout "$TIMEOUT" java -Xms256m -Xmx"$HEAP" -Xss128m superc.SuperC \
        -nostdinc -keepErrors -presenceConditions -configurationVariables -silent \
        -sourcelinePC "$out" $FLAG_ARGS "$file") > "$log" 2>&1
    code=$?
    printf '%s\t%s\t%s\n' "$file" "$code" "$(( $(date +%s) - start ))" >> /out/status.tsv
}
export -f analyse

total=$(grep -c . /out/files.txt)
echo "SuperC on $total file(s), $JOBS at a time, at most ${TIMEOUT}s each"
grep . /out/files.txt | xargs -d '\n' -P "$JOBS" -I{} bash -c 'analyse "$1"' _ {}
ok=$(awk -F'\t' '$2 == 0' /out/status.tsv | wc -l)
timed_out=$(awk -F'\t' '$2 == 124' /out/status.tsv | wc -l)
echo "Done: $ok of $total file(s) analysed, $timed_out timed out, $(( total - ok - timed_out )) failed"
