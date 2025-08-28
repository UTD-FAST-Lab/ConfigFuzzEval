import json
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

def request_configurations(grammar_file):
    """Main function that replicates the original script behavior."""
    grammar = load_grammar(grammar_file)
    
    # Adding manual configuration
    benchmark_name = grammar['name']
    
    if benchmark_name == "libxml2_xmllint":
        return [
            "--disable-shared --without-debug --without-http --without-python --with-zlib --with-lzma"
        ]
    elif benchmark_name == "pcre2_pcre2test":
        return [
            "--enable-fuzz-support --enable-never-backslash-C --with-match-limit=1000000 --with-match-limit-depth=1000000 --enable-pcre2-16 --enable-pcre2-32"]
    elif benchmark_name == "libpng_pngimage":
        return [""]
    elif benchmark_name == "bison_bison":
        return [""]
    elif benchmark_name == "file_file":
        return ["--enable-static --enable-fsect-man5"]
    elif benchmark_name == "expat_xmlwf":
        return [""]