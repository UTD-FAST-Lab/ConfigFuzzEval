"""
Grammar Configuration Module

This module provides functionality to load grammar configurations from JSON files
and generate CLI arguments based on option relationships and constraints.
"""

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


def option_to_cli(opt: Dict[str, Any]) -> str:
    """
    Convert option and value to CLI argument string.
    
    Args:
        opt: Option configuration
        val: Option value
        
    Returns:
        CLI argument string, empty if not applicable
    """

    if opt["type"] != "bool":
        return ""
    
    cli_type = opt["cli"].strip("-").split("-")[0]

    if cli_type == "enable":
        return f"--disable-{opt['name']}"
    elif cli_type == "with":
        return f"--without-{opt['name']}"
    else:
        print("Error! Invalid cli values present in the ct_grammar.json file for the option:",opt["name"])
        print("Skipping this option")
        return ""
    


def generate_cli_args(grammar: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> List[str]:
    """
    Generate CLI arguments from configuration.
    
    Args:
        grammar: Grammar configuration dictionary
        config: Configuration dictionary. If None, generates all-enabled config.
        
    Returns:
        List of CLI argument strings
    """
    
    cli_args = []
    for opt in grammar["options"]:
        if "override" in opt:
            print(f"Manual Override applied to option:{opt['name']} with {opt['override']}")
            print()
            arg = opt["override"]
        else:
            arg = option_to_cli(opt)
        if arg:
            cli_args.append(arg)
    
    
    return cli_args


def generate_cli_string(grammar: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> str:
    """
    Generate CLI arguments as a single string.
    
    Args:
        grammar: Grammar configuration dictionary
        config: Configuration dictionary. If None, generates all-enabled config.
        
    Returns:
        Space-separated CLI arguments string
    """
    return " ".join(generate_cli_args(grammar, config))


def request_configurations(grammar_file):
    """Main function that replicates the original script behavior."""
    grammar = load_grammar(grammar_file)
    cli_string = generate_cli_string(grammar)
    return [cli_string]


def main():

    grammar_file = "benchmarks/bison_bison/ct_grammar.json"
    print(request_configurations(grammar_file))

if __name__ == "__main__":
    main()