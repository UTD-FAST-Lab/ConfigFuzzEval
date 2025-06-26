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


def get_option(grammar: Dict[str, Any], name: str) -> Dict[str, Any]:
    """
    Get option configuration by name.
    
    Args:
        grammar: Grammar configuration dictionary
        name: Option name to find
        
    Returns:
        Option configuration dictionary
        
    Raises:
        StopIteration: If option not found
    """
    return next(opt for opt in grammar["options"] if opt["name"] == name)


def set_option(config: Dict[str, Any], name: str, value: Any) -> None:
    """
    Set option value in configuration.
    
    Args:
        config: Configuration dictionary to modify
        name: Option name
        value: Value to set
    """
    config[name] = value


def apply_implies(config: Dict[str, Any], opt: Dict[str, Any]) -> None:
    """
    Apply implied relationships for an option.
    
    Args:
        config: Configuration dictionary to modify
        opt: Option configuration with potential "implies" key
    """
    if "implies" not in opt:
        return
        
    for imp in opt["implies"]:
        # Format: "option" or "option=value"
        if "=" in imp:
            iname, ival = imp.split("=", 1)
            ival = ival.strip().lower() == "true"
        else:
            iname, ival = imp, True
        set_option(config, iname.strip(), ival)


def check_conflicts(config: Dict[str, Any], opt: Dict[str, Any], value: Any) -> bool:
    """
    Check if enabling an option would conflict with existing configuration.
    
    Args:
        config: Current configuration
        opt: Option configuration
        value: Proposed value for the option
        
    Returns:
        True if there would be a conflict, False otherwise
    """
    if not value or "conflicts" not in opt:
        return False
        
    for conflict in opt["conflicts"]:
        if config.get(conflict) is True:
            return True
    return False


def check_requires(config: Dict[str, Any], opt: Dict[str, Any], value: Any) -> bool:
    """
    Check if an option's requirements are met.
    
    Args:
        config: Current configuration
        opt: Option configuration
        value: Proposed value for the option
        
    Returns:
        True if requirements are met, False otherwise
    """
    if not value or "requires" not in opt:
        return True
        
    for req in opt["requires"]:
        if not config.get(req, False):
            return False
    return True


def generate_all_enabled_config(grammar: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate configuration with all options enabled where possible.
    
    Args:
        grammar: Grammar configuration dictionary
        
    Returns:
        Configuration dictionary with options set based on constraints
    """
    config = {}
    
    # First pass: set all options to enabled if possible
    for opt in grammar["options"]:
        # Skip minimum option or set it to False
        if opt["name"] == "minimum":
            set_option(config, opt["name"], False)
            continue
            
        # Set values based on type
        if opt["type"] == "bool":
            # Check conflicts and requirements
            if check_conflicts(config, opt, True) or not check_requires(config, opt, True):
                set_option(config, opt["name"], False)
            else:
                set_option(config, opt["name"], True)
        elif opt["type"] == "enum":
            set_option(config, opt["name"], opt["values"][0])
        elif opt["type"] == "depends":
            set_option(config, opt["name"], True)
        elif opt["type"] == "str":
            set_option(config, opt["name"], "/usr")
        
        # Apply implied relationships
        apply_implies(config, opt)
    
    # Second pass: resolve conflicts
    for opt in grammar["options"]:
        if "conflicts" in opt and config.get(opt["name"], False):
            for conflict in opt["conflicts"]:
                if config.get(conflict, False):
                    # Prefer enabling current option, disable conflicting one
                    config[conflict] = False
    
    # Third pass: disable options whose requirements aren't met
    for opt in grammar["options"]:
        if "requires" in opt and config.get(opt["name"], False):
            for req in opt["requires"]:
                if not config.get(req, False):
                    config[opt["name"]] = False
    
    return config


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

    grammar_file = "benchmarks/pcre2_pcre2test/ct_grammar.json"
    print(request_configurations(grammar_file))

if __name__ == "__main__":
    main()