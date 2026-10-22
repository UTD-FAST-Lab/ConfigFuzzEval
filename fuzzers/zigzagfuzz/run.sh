# A time limit when RUNTIME > 0 (evaluation mode); none when it is 0 or unset (continuous mode).
LIMIT=""; [ "${RUNTIME:-0}" -gt 0 ] 2>/dev/null && LIMIT="-V $RUNTIME"
/fuzzer/afl-fuzz -i /benchmark/seed -o $OUT -K 2 -a /benchmark/dict $LIMIT $RUN_TARGET 