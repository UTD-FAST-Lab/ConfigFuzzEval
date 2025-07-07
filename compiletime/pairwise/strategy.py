"""
Grammar Configuration Module

This module provides functionality to load grammar configurations from JSON files
and generate CLI arguments based on option relationships and constraints.
"""

import json
from typing import Dict, List, Any, Optional
from collections import OrderedDict
from allpairspy import AllPairs
import inspect


def implies(A,B):
    return (not A) or B

def get_all_attributes(obj):
    return {
        name: value
        for name, value in inspect.getmembers(obj)
        if not name.startswith('__') and not inspect.isroutine(value)
    }



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


def option_to_cli(config_sample: Any,grammar: Dict[str,Any]) -> str:
    """
    Convert option and value to CLI argument string.
    
    Args:
        opt: Option configuration
        val: Option value
        
    Returns:
        CLI argument string, empty if not applicable
    """
    args=[]

    for opt,val in config_sample.items():
        arg = None
        if grammar[opt]["type"]=="bool":
            arg = f"--{val}-{opt}" # for boolean values, value will be either enable or diable
        elif grammar[opt]["type"]=="enum":
            arg  = f"--enable-{opt}={val}"
        else:
            raise ValueError("Invalid Type, the Grammar Options must be of type: [enum,bool]")
        args.append(arg)
    
    return args

def generate_filter_functions(config,grammar):
    options = list(config.keys())
    indices = [i for i in range(len(options))]

    def filter_function(row):
        idx_mapping = dict(zip(options,indices))
        grammar_inner = dict(grammar)

        for key,value in grammar_inner.items():
            if "pairwise_constraints" not in value:
                continue

            for const_val,const_opts in value["pairwise_constraints"]:
                for opt,opt_val in const_opts:
                    o1 = key
                    o2 = opt
                    o1_val = row[idx_mapping[o1]]
                    o2_val = row[idx_mapping[o2]]

                    if not implies(o1_val==const_val, o2_val==opt_val):
                        return False 

        return True
    
    return filter_function

    
    
def filter_discrete_options(grammar):
    """
    Filters the given grammar to include only options with discrete types ('enum' or 'bool').

    Args:
        grammar (dict): A dictionary representing a parameter grammar, which must contain
                        an 'options' key with a list of option dictionaries. Each option
                        should have a 'type' key.

    Returns:
        dict: A new grammar dictionary containing only the filtered 'enum' and 'bool' options.
    """
    new_grammar = dict(grammar)
    filtered_opts = [opt for opt in new_grammar["options"] if opt["type"] in ["enum","bool"]]
    new_grammar["options"] = filtered_opts
    return new_grammar

def get_config_dict(grammar: Dict[str, Any]):
    
    config = OrderedDict()
    for opt in grammar["options"]:
        name = opt["name"]
        if opt["type"]=="bool":
            values = ["enable","disable"]
        elif opt["type"]=="enum":
            values = opt["values"]
        else:
            raise ValueError("Invalid Type, the Grammar Options must be of type: [enum,bool]")
        config[name]=values
    
    return config



def generate_cli_args(grammar: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> List[str]:
    """
    Generate CLI arguments from configuration.
    
    Args:
        grammar: Grammar configuration dictionary
        config: Configuration dictionary. If None, generates all-enabled config.
        
    Returns:
        List of CLI argument strings
    """

    grammar_filtered = filter_discrete_options(grammar)
    grammar_dict = dict(zip(list(map(lambda x: x["name"],grammar_filtered["options"])),grammar_filtered["options"]))
    
    config_dict = get_config_dict(grammar_filtered)
    config_vals = list(config_dict.values())
    samples = AllPairs(config_vals)
    samples = [OrderedDict(zip(config_dict.keys(),sample)) for sample in samples]

    filter_function = generate_filter_functions(config_dict,grammar_dict)
    for i,row in enumerate(samples):
        print(f"------------------Sample {i+1}------------------")
        print(json.dumps(row,indent=4))
        print()
        print("Truth Value:",filter_function(list(row.values())))
        print(f"------------------------------------------------")
        print()
        print()
    
    cli_args = [option_to_cli(sample,grammar_dict) for sample in samples]
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
    return [" ".join(cli_args) for cli_args in generate_cli_args(grammar, config)]


def request_configurations(grammar_file):
    """Main function that replicates the original script behavior."""
    grammar = load_grammar(grammar_file)
    cli_string = generate_cli_string(grammar)
    return cli_string


def main():

    grammar_file = "benchmarks/libxml2_xmllint/ct_grammar.json"
    cli_strings = request_configurations(grammar_file)
    for s in cli_strings:
        print(s)
        print()
        print()

if __name__ == "__main__":
    main()