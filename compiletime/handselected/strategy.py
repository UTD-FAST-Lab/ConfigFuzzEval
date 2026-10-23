import json
import os
import re
from typing import Dict, List, Any, Optional

def load_grammar(grammar_file) -> Dict[str, Any]:
    """
    Load grammar configuration from JSON file.
    
    Args:
        grammar_file: Path to the grammar JSON file
        
    Returns:
        Grammar configuration dictionary
    """
    with open(grammar_file, "r") as f:
        return json.load(f)

def check_flags(grammar_file, grammar, config):
    """Warn about flags that build.sh already passes, or that name an option that is
    neither in the grammar nor in its "removed" list."""
    with open(os.path.join(os.path.dirname(grammar_file), "build.sh")) as f:
        hardcoded = {m.group(2) for m in re.finditer(r"--(enable|disable|with|without)-([\w+-]+)", f.read())}
    known = {o["name"] for o in grammar["options"]} | {r["name"] for r in grammar.get("removed", [])}
    for flag in config.split():
        m = re.match(r"--(enable|disable|with|without)-([\w+-]+)", flag)
        if not m:
            continue
        if m.group(2) in hardcoded:
            print(f"Warning: hand-selected configuration of {grammar['name']}: {flag} is already set by build.sh")
        elif m.group(2) not in known:
            print(f"Warning: hand-selected configuration of {grammar['name']}: {flag} is not an option of the grammar")


def request_configurations(grammar_file, random_seed=None):
    """Main function that replicates the original script behavior."""
    grammar = load_grammar(grammar_file)
    configs = manual_configurations(grammar)
    for config in configs:
        check_flags(grammar_file, grammar, config)
    return configs


def manual_configurations(grammar):
    # Adding the hand-selected configuration
    benchmark_name = grammar['name']
    
    if benchmark_name == "libxml2_xmllint":
        return [
            "--without-debug --without-http --with-zlib"
        ]
    elif benchmark_name == "pcre2_pcre2test":
        return [
            "--enable-fuzz-support --enable-never-backslash-C --with-match-limit=1000000 --with-match-limit-depth=1000000 --enable-pcre2-16 --enable-pcre2-32"]
    elif benchmark_name == "libpng_pngimage":
        return [""]
    elif benchmark_name == "bison_bison":
        return [""]
    elif benchmark_name == "file_file":
        return ["--enable-fsect-man5"]
    elif benchmark_name == "expat_xmlwf":
        return [""]
    elif benchmark_name == "libtiff_tiff2pdf":
        return [""]
    elif benchmark_name == "binutils_nm-new":
        return [""]
    elif benchmark_name == "binutils_objdump":
        return [""]
    elif benchmark_name == "xz_xz":
        return [""]
    elif benchmark_name == "x264_x264":
        return [""]
    elif benchmark_name == "ffmpeg_ffmpeg":
        return [""]
    # No hand-selected configuration for this benchmark: build with build.sh's own flags only.
    return [""]
