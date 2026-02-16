"""
Grammar Configuration Module - Maximum Strategy (New Format)

This module provides functionality to load grammar configurations from the new
JSON format and generate CLI arguments. It implements a "Maximum" strategy,
attempting to enable all features unless explicitly constrained.
"""

import json
from typing import Dict, List, Any, Optional
import random


def calculate_constraint_score(rule: Dict[str, Any]) -> int:
    """
    Calculate the priority score of a constraint rule.
    Formula: (Count of forces True) - (Count of forces False).
    
    Positive Score: Forces more options ON (High Priority).
    Negative Score: Forces more options OFF (Low Priority).
    """
    score = 0
    for consequence in rule.get("then", []):
        # Check for explicit boolean assignments
        if "val" in consequence:
            val = consequence["val"]
            if val is True:
                score += 1
            elif val is False:
                score -= 1
            # Handle Choice Operators
            elif val == "==": 
                 # Forces a specific value -> effectively "Enabling" a specific state (+1)
                 score += 1
            elif val == "!=":
                 # Restricts a value -> effectively "Disabling" a specific state (-1)
                 score -= 1
    return score



def load_grammar(grammar_file) -> Dict[str, Any]:
    """
    Load grammar configuration from JSON file.
    Args:
        grammar_file: Path to the grammar JSON file.
    Returns:
        Grammar configuration dictionary.
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



def apply_constraints(grammar: Dict[str, Any], config: Dict[str, Any], sorted_constraints: List[Any]) -> bool:
    """
    Iterate through the pre-sorted constraints and enforce them.
    
    Args:
        grammar: Used for looking up option definitions (get_option)
        config: Current configuration state
        sorted_constraints: List of constraint rules, already sorted by priority
    """
    changed = False

    for rule in sorted_constraints:
        # Check if the 'condition' (if) part of the rule matches current config
        trigger_opt = rule.get("opt")
        trigger_val = rule.get("val")
        
        if trigger_opt not in config:
            continue
        
        if config[trigger_opt] == trigger_val:
            
            # Apply the 'consequences' (then) part of the rule
            for consequence in rule.get("then", []):
                target_opt = consequence.get("opt")
                
                target_def = get_option(grammar, target_opt)
                if not target_def:
                    continue
                
                # Case A: Comparison Constraint
                if "choice" in consequence and "val" in consequence:
                    operator = consequence["val"]
                    forbidden_choice = consequence["choice"]
                    current_val = config.get(target_opt)

                    if operator == "!=":
                        if current_val == forbidden_choice:
                            if "choices" in target_def:
                                valid_choices = [c for c in target_def["choices"] if c != forbidden_choice]
                                if valid_choices:
                                    new_val = random.choice(valid_choices)
                                    if config.get(target_opt) != new_val:
                                        set_option(config, target_opt, new_val)
                                        changed = True
                                        
                    elif operator == "==":
                        if config.get(target_opt) != forbidden_choice:
                            set_option(config, target_opt, forbidden_choice)
                            changed = True

                # Case B: Direct Assignment
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
    1. Bools -> Set to True.
    2. Choices -> Set to Random "Truthy" value (avoid False if possible).
    """
    config = {}
    
    # --- PASS 1: GREEDY INITIALIZATION ---
    for opt in grammar["options"]:
        name = opt["name"]
        
        if name == "minimum":
            set_option(config, name, False)
            continue
            
        if opt["type"] == "bool":
            set_option(config, name, True)
            
        elif opt["type"] == "choice":
            if "choices" in opt and len(opt["choices"]) > 0:
                # [FIX] Filter out 'False' to ensure we start with a Maximum configuration.
                # We want True, strings, numbers, etc. We do NOT want to randomly pick False.
                truthy_choices = [c for c in opt["choices"] if c is not False]
                
                if truthy_choices:
                    set_option(config, name, random.choice(truthy_choices))
                else:
                    # If the ONLY choices are False (rare), we must pick it.
                    set_option(config, name, random.choice(opt["choices"]))
            else:
                set_option(config, name, "")
                
    # --- PASS 2: PRE-PROCESSING CONSTRAINTS (Done ONCE) ---
    if "constraints" in grammar:
        # 1. Annotate constraints with their calculated scores
        scored_constraints = []
        for rule in grammar["constraints"]:
            score = calculate_constraint_score(rule)
            scored_constraints.append((score, rule))
        
        # 2. Randomize first (to break ties randomly)
        random.shuffle(scored_constraints)
        
        # 3. Sort by score ascending (Low score first -> High score last)
        scored_constraints.sort(key=lambda x: x[0])
        
        # 4. Extract just the rules
        final_constraint_list = [rule for score, rule in scored_constraints]
    else:
        final_constraint_list = []

    # --- PASS 3: CONSTRAINT SOLVER LOOP ---
    max_iterations = 10
    iteration = 0
    while iteration < max_iterations:
        did_change = apply_constraints(grammar, config, final_constraint_list)
        if not did_change:
            break
        iteration += 1
        
    return config



def option_to_cli(opt: Dict[str, Any], val: Any) -> str:
    """
    Convert option and value to CLI argument string.
    
    [UPDATED] 'depends' type is removed. 'choice' type handles everything.
    - If val is boolean (True/False): outputs flag only (e.g., --with-zlib)
    - If val is string/int: outputs flag=value (e.g., --with-zlib=/usr)
    """
    cli_style = opt.get("cli", "with") # default to 'with' if missing
    name = opt["name"]

    # Helper for boolean formatting logic
    def format_bool(is_true: bool):
        if is_true:
            return f"--{cli_style}-{name}"
        else:
            negation = "disable" if cli_style == "enable" else "without"
            return f"--{negation}-{name}"

    if opt["type"] == "bool":
        return format_bool(val is True)
            
    elif opt["type"] == "choice":
        # [UPDATED] Check for boolean types first (e.g., zlib: true)
        if isinstance(val, bool):
            return format_bool(val)
        
        # Standard string/int choices (e.g., prefix: "/usr")
        if val is not None and val != "":
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