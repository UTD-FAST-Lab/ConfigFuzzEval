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


def holds(config: Dict[str, Any], cond: Dict[str, Any]) -> bool:
    """Whether a condition {"opt", "val", optional "choice": "=="/"!="} or {"or": [...]} holds."""
    if "or" in cond:
        return any(holds(config, branch) for branch in cond["or"])
    same = config.get(cond.get("opt")) == cond.get("val")
    return not same if cond.get("choice") == "!=" else same


def enforce(grammar: Dict[str, Any], config: Dict[str, Any], cond: Dict[str, Any]) -> None:
    """Change the configuration so that a condition holds. For an "or", the first
    branch is enforced, so the grammar's order sets the preference."""
    if "or" in cond:
        enforce(grammar, config, cond["or"][0])
        return
    name, val = cond["opt"], cond["val"]
    if cond.get("choice") != "!=":
        config[name] = val
        return
    opt = next(o for o in grammar["options"] if o["name"] == name)
    others = [c for c in opt.get("choices", [True, False]) if c != val]
    if others:
        config[name] = others[0]


def generate_minimum_config(grammar: Dict[str, Any]) -> Dict[str, Any]:
    """Every bool option off and every choice option at its default (not passed),
    then the grammar's constraints applied, in grammar order, until they all hold.
    Deterministic, like compiletime/maximum and the runtime mostdisabled strategy."""
    config = {opt["name"]: False if opt["type"] == "bool" else opt.get("default")
              for opt in grammar["options"]}
    names = set(config)
    rules = grammar.get("constraints", [])
    for _ in range(10):
        changed = False
        for rule in rules:
            if rule.get("opt") not in names or not holds(config, rule):
                continue
            for then in rule.get("then", []):
                if not holds(config, then):
                    enforce(grammar, config, then)
                    changed = True
        if not changed:
            break
    else:
        print("Warning: the constraints could not all be satisfied for the minimum configuration")
    return config


def option_to_cli(opt: Dict[str, Any], val: Any) -> str:
    """
    Convert option and value to CLI argument string.

    Args:
        opt: Option configuration
        val: Option value

    Returns:
        CLI argument string, empty if not applicable
    """
    cli_type = opt.get("cli", "enable").strip("-").split("-")[0]
    if cli_type not in ("enable", "with"):
        print("Error! Invalid cli values present in the ct_grammar.json file for the option:",opt["name"])
        print("Skipping this option")
        return ""

    if isinstance(val, bool):
        if val:
            return f"--{cli_type}-{opt['name']}"
        return f"--{'disable' if cli_type == 'enable' else 'without'}-{opt['name']}"
    if val is None or val == "":
        return ""
    return f"--{cli_type}-{opt['name']}={val}"



def generate_cli_args(grammar: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> List[str]:
    """
    Generate CLI arguments from configuration.

    Args:
        grammar: Grammar configuration dictionary
        config: Configuration dictionary. If None, generates the minimum config.

    Returns:
        List of CLI argument strings
    """
    if config is None:
        config = generate_minimum_config(grammar)

    cli_args = []
    for opt in grammar["options"]:
        if "override" in opt:
            print(f"Manual Override applied to option:{opt['name']} with {opt['override']}")
            print()
            arg = opt["override"]
        elif opt["type"] == "bool" or config[opt["name"]] != opt.get("default"):
            # Choice options are only passed when a constraint moved them off their default
            arg = option_to_cli(opt, config[opt["name"]])
        else:
            arg = ""
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


def request_configurations(grammar_file, random_seed=None):
    """Main function that replicates the original script behavior. Deterministic:
    random_seed is accepted like every strategy's, but not needed."""
    grammar = load_grammar(grammar_file)
    cli_string = generate_cli_string(grammar)
    return [cli_string]


def main():

    grammar_file = "benchmarks/bison_bison/ct_grammar.json"
    print(request_configurations(grammar_file))

if __name__ == "__main__":
    main()