#!/bin/bash
# CarpetFuzz's offline analysis for a benchmark. Writes into benchmarks/<name>/carpetfuzz/:
#   relation.json             option conflicts/dependencies found in manpage.1 (find_relationship.py)
#   relation_simplified.json  the same, restricted to the top options by coverage,
#                             when there are more than $MAX_OPTIONS (simplify.py)
#   combinations.txt          valid 6-wise option combinations (PICT), ranked at trial start
# dict.json (option values) comes from make_dict.py.
#
# Usage: fuzzers/carpetfuzz/analysis/generate.sh <benchmark> ...
# Needs: docker images fbpp/carpetfuzz-analysis (this directory's Dockerfile),
# fbpp/fuzzer:carpetfuzz and fbpp/runner (built by common/run_experiment.py).
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
ANALYSIS=$ROOT/fuzzers/carpetfuzz/analysis
MAX_OPTIONS=50   # CarpetFuzz's default for simplify_relationship.py
WORK=$(mktemp -d)
trap 'docker run --rm -v "$WORK":/w fbpp/runner rm -rf /w/fuzzer /w/bench >/dev/null 2>&1; rm -rf "$WORK"' EXIT

in_analysis() {  # in_analysis <benchmark dir> <command>: run in fbpp/carpetfuzz-analysis
  docker run --rm -v "$1":/bench -v "$ANALYSIS":/tools:ro fbpp/carpetfuzz-analysis \
    bash -c "$2; chown -R $(id -u):$(id -g) /bench/carpetfuzz"
}

for b in "$@"; do
  B=$ROOT/benchmarks/$b
  mkdir -p "$B/carpetfuzz"
  [ -f "$B/carpetfuzz/dict.json" ] || { echo "[x] $b: run make_dict.py first" >&2; exit 1; }

  echo "[*] $b: extracting option relationships from manpage.1"
  in_analysis "$B" "cd scripts && python3 find_relationship.py --file /bench/manpage.1 >&2 && cp ../output/relation/relation_*.json /bench/carpetfuzz/relation.json"
  # CarpetFuzz's man page parser also lists "-" (stdin) and "--" (end of
  # options) as options; in a combination they turn the options after them
  # into file names, so drop them.
  python3 - "$B/carpetfuzz/relation.json" <<'EOF'
import json, sys
path = sys.argv[1]
rel = json.load(open(path))
o = rel["options"]
drop = {"-", "--"}
o["total_options"] = [x for x in o["total_options"] if x not in drop]
o["conflict_options"] = [p for p in o["conflict_options"] if not drop & set(p)]
o["dependent_options"] = {k: v for k, v in o["dependent_options"].items()
                          if k not in drop and not drop & set(v.replace("&&", " ").replace("||", " ").split())}
json.dump(rel, open(path, "w"))
EOF
  relation=relation.json
  rm -f "$B/carpetfuzz/relation_simplified.json"

  n=$(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))['options']['total_options']))" "$B/carpetfuzz/relation.json")
  if [ "$n" -gt "$MAX_OPTIONS" ]; then
    echo "[*] $b: $n options; simplifying to the $MAX_OPTIONS with the most dry-run coverage"
    # The benchmark's carpetfuzz build and the carpetfuzz fuzzer, laid out as in a trial.
    cp -r "$B" "$WORK/src"
    sed -i 's/{{CT_CONFIGURATION}}//' "$WORK/src/build.sh"
    docker build -q -t "fbpp/carpetfuzz-analysis-bench:$b" -f "$WORK/src/builder.Dockerfile" "$WORK/src" \
      --build-arg parent_image=fbpp/fuzzer:carpetfuzz \
      --build-arg FUZZER_COMP=/carpetfuzz/afl-clang-fast --build-arg FUZZER_COMPXX=/carpetfuzz/afl-clang-fast++ >/dev/null
    mkdir -p "$WORK/bench" "$WORK/fuzzer"
    docker run --rm -v "$WORK/bench":/benchmark_out_dir "fbpp/carpetfuzz-analysis-bench:$b"
    docker run --rm -v "$WORK/fuzzer":/fuzzer_output fbpp/fuzzer:carpetfuzz
    docker run --rm -u "$(id -u):$(id -g)" -v "$WORK/bench":/benchmark:ro -v "$WORK/fuzzer/carpetfuzz":/fuzzer:ro \
      -v "$ROOT/fuzzers/carpetfuzz":/cf:ro -v "$B/carpetfuzz":/out fbpp/runner \
      python3 /cf/analysis/simplify.py --relation /out/relation.json --dict /out/dict.json \
        --number "$MAX_OPTIONS" --bindir /benchmark --seeddir /benchmark/seed \
        --showmap /fuzzer/afl-showmap --out /out/relation_simplified.json
    docker run --rm -v "$WORK":/w fbpp/runner rm -rf /w/src /w/bench /w/fuzzer
    relation=relation_simplified.json
  fi

  echo "[*] $b: generating option combinations with PICT"
  # CarpetFuzz's generate_combination.py functions; the order is capped at the
  # number of options (the script always uses 6, which PICT rejects for fewer).
  in_analysis "$B" "cd scripts && python3 -c '
import json, sys
from generate_combination import generatePictModel, parsePictResult
from utils.execution_util import ExecutionUtil
relation = json.load(open(\"/bench/carpetfuzz/$relation\"))
order = min(6, len(relation[\"options\"][\"total_options\"]))
model = generatePictModel(\"target\", relation)
result = ExecutionUtil().executeCommand(\"../pict/build/cli/pict %s /c /o:%d\" % (model, order))
open(\"/bench/carpetfuzz/combinations.txt\", \"w\").write(\"\\n\".join(parsePictResult(result)) + \"\\n\")
' >&2"
  echo "[+] $b: $n options -> $(wc -l < "$B/carpetfuzz/combinations.txt") combinations ($relation)"
done
