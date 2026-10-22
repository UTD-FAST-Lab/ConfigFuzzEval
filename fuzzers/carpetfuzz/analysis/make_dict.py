#!/usr/bin/env python3
"""Build a benchmark's CarpetFuzz option-value dictionary (carpetfuzz/dict.json).

CarpetFuzz turns an option combination into a command by giving each option
that takes an argument a value from a hand-written dictionary
(CarpetFuzz/tests/dict/dict.json, 49 programs). We take the values from the
benchmark's rt_grammar.json, which lists them for our versions, and fall back
to CarpetFuzz's dictionary for options the grammar does not cover.

Output format (read by fuzzers/carpetfuzz/rank.py):
  {"synopsis": "<binary> OPTIONS <fixed args with @@>",
   "options": {"<opt>": {"connector": " " | "=" | "", "values": [...]}}}
The command is <opt><connector><value>; CarpetFuzz's own "=v"/"*v" prefixes are
converted to connectors (its restoreStub renders them as "opt==v"/"opt*v").
"""
import argparse
import json
import os


def grammar_values(option):
    if option["type"] == "choice":
        return [str(c) for c in option["choices"]]
    if option["type"] in ("intnum", "realnum") and "range" in option:
        low, high = option["range"]
        mid = (low + high) // 2 if option["type"] == "intnum" else (low + high) / 2
        return [str(v) for v in dict.fromkeys([low, mid, high])]
    return []


def carpetfuzz_entry(value):
    """CarpetFuzz dict value -> (connector, value)."""
    if value.startswith("="):
        return "=", value[1:]
    if value.startswith("*"):
        return "", value[1:]
    return " ", value


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--benchmark-dir", required=True, help="benchmarks/<name>")
    parser.add_argument("--carpetfuzz-dict", required=True, help="CarpetFuzz tests/dict/dict.json")
    parser.add_argument("--program", required=True, help="program name in CarpetFuzz's dictionary")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    with open(os.path.join(args.benchmark_dir, "run_target.sh")) as f:
        run_target = f.read().split()
    with open(os.path.join(args.benchmark_dir, "rt_grammar.json")) as f:
        grammar = json.load(f)
    with open(args.carpetfuzz_dict) as f:
        carpetfuzz = json.load(f).get(args.program, {"options": {}})

    # Same command as every other fuzzer runs, with the options inserted after
    # the binary (as in the grammars' "$inopts ..." cmdline).
    synopsis = " ".join([os.path.basename(run_target[0]), "OPTIONS"] + run_target[1:])

    options = {}
    for opt, values in carpetfuzz["options"].items():
        connector, _ = carpetfuzz_entry(values[0])
        options[opt] = {"connector": connector,
                        "values": [carpetfuzz_entry(v)[1] for v in values]}
    for option in grammar["options"]:
        values = grammar_values(option)
        if values:
            options[option["opt"]] = {"connector": option.get("connector", grammar.get("connector", " ")),
                                      "values": values}

    with open(args.out, "w") as f:
        json.dump({"synopsis": synopsis, "options": options}, f, indent=1)
    print(f"[+] {args.out}: {len(options)} options with values; synopsis: {synopsis}")


if __name__ == "__main__":
    main()
