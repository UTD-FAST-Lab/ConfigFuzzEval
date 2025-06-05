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
            "--disable-shared --without-debug --without-http --without-python",
            "--disable-shared --without-debug --without-http --without-python --with-zlib --with-lzma"
        ]