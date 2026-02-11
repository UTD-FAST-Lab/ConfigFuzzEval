# notes: we first set everything to true, the we sewquentially apply every constraint until we see no change occured in a pass. In this case, if 2 options set the same option as a constraint, lets say A needs b to be false and c needs b to be true, then we set b to true as C comes last.

"""
Grammar Configuration Module - Maximum Strategy (New Format)

This module provides functionality to load grammar configurations from the new
JSON format and generate CLI arguments. It implements a "Maximum" strategy,
attempting to enable all features unless explicitly constrained.
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


# [NEW] This function replaces check_conflicts/requires/implies
def apply_constraints(grammar: Dict[str, Any], config: Dict[str, Any]) -> bool:
    """
    Iterate through constraints and enforce them on the configuration.
    
    Args:
        grammar: The full grammar dict containing 'constraints'
        config: The current configuration state

    Returns:
        bool: True if any changes were made to the config (requires another pass),
              False if the config is stable.
    """
    if "constraints" not in grammar:
        return False

    changed = False

    for rule in grammar["constraints"]:
        # 1. Check if the 'condition' (if) part of the rule matches current config
        trigger_opt = rule.get("opt")
        trigger_val = rule.get("val")
        
        # If the option isn't in config, we can't evaluate the trigger
        if trigger_opt not in config:
            continue
        
        # Check if the trigger condition is met
        # e.g., if config["c14n"] == True
        if config[trigger_opt] == trigger_val:
            
            # 2. Apply the 'consequences' (then) part of the rule
            for consequence in rule.get("then", []):
                target_opt = consequence.get("opt")
                
                # Retrieve the target option definition to check for valid choices
                target_def = get_option(grammar, target_opt)
                if not target_def:
                    continue
                
                # Case A: Comparison Constraint (e.g., target != "choice 1")
                if "choice" in consequence and "val" in consequence:
                    operator = consequence["val"]
                    forbidden_choice = consequence["choice"]
                    current_val = config.get(target_opt)

                    if operator == "!=":
                        if current_val == forbidden_choice:
                            # [STRATEGY] If we must NOT be this choice, pick the next available valid one.
                            # For Maximum strategy, we usually just pick the first valid option 
                            # that isn't the forbidden one.
                            if "choices" in target_def:
                                for valid_c in target_def["choices"]:
                                    if valid_c != forbidden_choice:
                                        if config.get(target_opt) != valid_c:
                                            set_option(config, target_opt, valid_c)
                                            changed = True
                                        break
                    elif operator == "==":
                        # Force specific choice
                        if config.get(target_opt) != forbidden_choice:
                            set_option(config, target_opt, forbidden_choice)
                            changed = True

                # Case B: Direct Assignment (e.g., target = True / False)
                elif "val" in consequence:
                    target_val = consequence["val"]
                    if config.get(target_opt) != target_val:
                        set_option(config, target_opt, target_val)
                        changed = True

    return changed


def generate_all_enabled_config(grammar: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate configuration with all options enabled where possible.
    
    Strategy:
    1. Initialize all Bools to True and Choices to default/first value.
    2. Iteratively apply constraints until the configuration stabilizes.
    
    Args:
        grammar: Grammar configuration dictionary
        
    Returns:
        Configuration dictionary with options set based on constraints
    """
    config = {}
    
    # --- PASS 1: GREEDY INITIALIZATION ---
    # Set everything to its "Maximum" or "Default" state ignoring constraints initially
    for opt in grammar["options"]:
        name = opt["name"]
        
        # [UPDATED] Handle the new "minimum" exclusion logic if it exists
        if name == "minimum":
            set_option(config, name, False)
            continue
            
        # [UPDATED] Logic for the new 'bool' vs 'choice' types
        if opt["type"] == "bool":
            # Maximum strategy: Try to enable everything by default
            # unless the default is strictly enforced (optional: usually we force True)
            set_option(config, name, True)
            
        elif opt["type"] == "choice":
            # Maximum strategy: If a default exists, use it. 
            # Otherwise, pick the first available choice.
            if "default" in opt:
                set_option(config, name, opt["default"])
            elif "choices" in opt and len(opt["choices"]) > 0:
                set_option(config, name, opt["choices"][0])
            else:
                set_option(config, name, "")

        elif opt["type"] == "depends":
            # Maximum strategy: treat dependency flags like bools (enable by default)
            set_option(config, name, True)
                
    # --- PASS 2: CONSTRAINT SOLVER LOOP ---
    # [NEW] Instead of separate passes for conflicts/requires, we loop the constraints
    # until the configuration stops changing. This handles chains (A->B->C).
    max_iterations = 10  # Prevent infinite loops in case of cyclic constraints
    iteration = 0
    while iteration < max_iterations:
        did_change = apply_constraints(grammar, config)
        if not did_change:
            break
        iteration += 1
        
    return config


def option_to_cli(opt: Dict[str, Any], val: Any) -> str:
    """
    Convert option and value to CLI argument string.
    
    Args:
        opt: Option configuration
        val: Option value
        
    Returns:
        CLI argument string, empty if not applicable
    
    [UPDATED] Handles the new format where CLI style (with/enable) is explicitly defined.
    """
    cli_style = opt.get("cli", "with") # default to 'with' if missing
    name = opt["name"]

    if opt["type"] == "bool":
        if val is True:
            # e.g., --enable-foo or --with-foo
            return f"--{cli_style}-{name}"
        else:
            # e.g., --disable-foo or --without-foo
            negation = "disable" if cli_style == "enable" else "without"
            return f"--{negation}-{name}"
    elif opt["type"] == "depends":
        if val is True:
            return f"--{cli_style}-{name}"
        if val is False:
            negation = "disable" if cli_style == "enable" else "without"
            return f"--{negation}-{name}"
        if val is not None and val != "":
            return f"--{cli_style}-{name}={val}"
            
    elif opt["type"] == "choice":
        # e.g., --with-default-strip-size=8192
        # Choices usually imply a value assignment, so we check if it's not empty/false
        if val is not None and val != "":
             # For choices, we almost always use the positive form + value
             return f"--{cli_style}-{name}={val}"
             
    return ""


def generate_cli_args(grammar: Dict[str, Any],
                     config: Optional[Dict[str, Any]] = None) -> List[str]:
    """
    Generate CLI arguments from configuration.
    
    Args:
        grammar: Grammar configuration dictionary
        config: Configuration dictionary. If None, generates all-enabled config.
        
    Returns:
        List of CLI argument strings
    """
    if config is None:
        config = generate_all_enabled_config(grammar)
    
    cli_args = []
    for opt in grammar["options"]:
        arg = option_to_cli(opt, config[opt["name"]])
        if arg:
            cli_args.append(arg)
    
    return cli_args


def generate_cli_string(grammar: Dict[str, Any],
                        config: Optional[Dict[str, Any]] = None) -> str:
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


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python strategy.py <grammar_file>")
        sys.exit(1)
    
    grammar_file = sys.argv[1]
    configurations = request_configurations(grammar_file)
    for config in configurations:
        print(config)