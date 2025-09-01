# Grammar Configuration Module
# (updated: fixes constraint matching and CLI generation)

import json
from typing import Dict, List, Any, Optional
from collections import OrderedDict
from allpairspy import AllPairs
import inspect


def implies(A,B):
    """
    Perform logical implication A ⇒ B.

    Args:
        A: Antecedent of the implication
        B: Consequent of the implication

    Returns:
        Result of the implication (True if (not A) or B)
    """
    return (not A) or B



def load_grammar(grammar_file) -> Dict[str, Any]:
    """
    Load grammar configuration from JSON file.
    """
    with open(grammar_file, "r") as f:
        return json.load(f)


def option_to_cli(config_sample: Any, grammar: Dict[str, Any]) -> List[str]:
    """
    Convert option and value to CLI argument strings.

    Args:
        config_sample: OrderedDict of {option_name: chosen_value}
        grammar: mapping option_name -> option metadata

    Returns:
        list of CLI argument strings for this sample
    """
    args = []

    for opt, val in config_sample.items():
        arg = None
        meta = grammar.get(opt)
        if meta is None:
            # skip unknown option
            continue

        # detect CLI prefix (enable / with)
        cli_prefix = meta.get("cli", "").lstrip("-").split("-")[0] if "cli" in meta else None

        if meta["type"] == "bool":
            # expecting val to be strings like "enable"/"disable" or "with"/"without"
            # produce "--enable-<opt>" or "--with-<opt>"
            arg = f"--{val}-{opt}"
        elif meta["type"] == "enum":
            # use the CLI prefix from the grammar (usually "with")
            if cli_prefix:
                arg = f"--{cli_prefix}-{opt}={val}"
            else:
                # fallback
                arg = f"--{opt}={val}"
        else:
            raise ValueError("Invalid Type, the Grammar Options must be of type: [enum,bool]")

        args.append(arg)

    return args


def _bool_to_token(opt_name: str, boolean: bool, grammar: Dict[str, Any]) -> str:
    """
    Map a boolean constraint value to the token used in the AllPairs rows,
    depending on the option's CLI prefix (enable/with).
    """
    meta = grammar.get(opt_name)
    if not meta:
        # default mapping
        return "enable" if boolean else "disable"

    cli = meta.get("cli", "")
    cli_prefix = cli.lstrip("-").split("-")[0] if cli else None

    if cli_prefix == "enable":
        return "enable" if boolean else "disable"
    elif cli_prefix == "with":
        return "with" if boolean else "without"
    else:
        # fallback: use enable/disable
        return "enable" if boolean else "disable"


def _normalize_constraint_value(opt_name: str, val: Any, grammar: Dict[str, Any]) -> Any:
    """
    Convert a constraint value (which may be boolean True/False or a string)
    into the value that appears in the AllPairs row (e.g. "with"/"without" or enum string).
    """
    if isinstance(val, bool):
        return _bool_to_token(opt_name, val, grammar)
    else:
        # enum or already tokenized string -> leave unchanged
        return val


def generate_filter_functions(config, grammar):
    """
    Generate a filter function to enforce pairwise constraints from grammar.

    Args:
        config: Dictionary mapping option names to their possible values
        grammar: Dictionary containing option metadata and pairwise constraints

    Returns:
        A function that takes a row (list/tuple of option values) and returns True if it satisfies all constraints,
        otherwise False
    """
    options = list(config.keys())
    idx_mapping = dict(zip(options, range(len(options))))

    # Build a unified list of constraints from both pairwise_constraints and implies
    # Each entry will be a tuple: (antecedent_option, antecedent_value, list_of[(consequent_option, consequent_value), ...])
    constraints = []

    for opt_name, meta in grammar.items():
        # pairwise_constraints already in structured format
        pc = meta.get("pairwise_constraints")
        if pc:
            for const_val, const_opts in pc:
                constraints.append((opt_name, const_val, const_opts))

        # also support 'implies' strings like "output=true"
        imps = meta.get("implies")
        if imps:
            for imp in imps:
                if isinstance(imp, str):
                    # parse "opt=val"
                    if "=" in imp:
                        other, val_str = imp.split("=", 1)
                        # interpret value strings "true"/"false" (case-insensitive)
                        if val_str.lower() == "true":
                            parsed_val = True
                        elif val_str.lower() == "false":
                            parsed_val = False
                        else:
                            parsed_val = val_str
                        # implies is interpreted as: when opt_name == True => other == parsed_val
                        constraints.append((opt_name, True, [[other, parsed_val]]))
                elif isinstance(imp, list):
                    # handle list of "opt=val" strings (if present)
                    parsed = []
                    for item in imp:
                        if isinstance(item, str) and "=" in item:
                            other, val_str = item.split("=", 1)
                            if val_str.lower() == "true":
                                parsed_val = True
                            elif val_str.lower() == "false":
                                parsed_val = False
                            else:
                                parsed_val = val_str
                            parsed.append([other, parsed_val])
                    if parsed:
                        constraints.append((opt_name, True, parsed))

    def filter_function(row):
        """
        row: tuple or list with values in same order as config keys
        """
        n = len(row)
        # check constraints
        for antecedent_opt, antecedent_val, consequents in constraints:
            # skip constraints that reference options not in the discrete config space
            if antecedent_opt not in idx_mapping:
                continue

            a_idx = idx_mapping[antecedent_opt]
            if a_idx >= n:
                continue

            # normalize expected antecedent token (e.g., True -> "with"/"enable")
            expected_a_token = _normalize_constraint_value(antecedent_opt, antecedent_val, grammar)
            row_a_token = row[a_idx]

            # if antecedent holds, check consequents
            if row_a_token == expected_a_token:
                for (c_opt, c_val) in consequents:
                    if c_opt not in idx_mapping:
                        # if consequent option not part of this discrete config, ignore constraint
                        continue
                    c_idx = idx_mapping[c_opt]
                    if c_idx >= n:
                        continue
                    expected_c_token = _normalize_constraint_value(c_opt, c_val, grammar)
                    row_c_token = row[c_idx]
                    if row_c_token != expected_c_token:
                        return False  # constraint violated

        return True

    return filter_function


def filter_discrete_options(grammar, return_override=False):
    """
    Filters the given grammar to include only options with discrete types ('enum' or 'bool').
    """
    new_grammar = dict(grammar)
    filtered_opts = [opt for opt in new_grammar["options"] if (opt["type"] in ["enum", "bool"]) and ("override" not in opt)]
    override_opts = [opt["override"] for opt in new_grammar["options"] if "override" in opt]
    new_grammar["options"] = filtered_opts
    if return_override:
        return new_grammar, override_opts
    else:
        return new_grammar


def get_config_dict(grammar: Dict[str, Any]):
    """
    Convert grammar options into a configuration dictionary used for AllPairs.
    """
    config = OrderedDict()
    for opt in grammar["options"]:
        name = opt["name"]
        cli_type = opt["cli"].lstrip("-").split("-")[0]
        if opt["type"] == "bool" and cli_type == "enable":
            values = ["enable", "disable"]
        elif opt["type"] == "bool" and cli_type == "with":
            values = ["with", "without"]
        elif opt["type"] == "enum":
            values = opt["values"]
        else:
            raise ValueError("Invalid Type, the Grammar Options must be of type: [enum,bool]")
        config[name] = values

    return config


def generate_cli_args(grammar: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> List[List[str]]:
    """
    Generate CLI argument lists from configuration.
    """
    grammar_filtered, grammar_override = filter_discrete_options(grammar, return_override=True)
    grammar_dict = dict(zip(list(map(lambda x: x["name"], grammar_filtered["options"])), grammar_filtered["options"]))

    config_dict = get_config_dict(grammar_filtered)
    config_vals = list(config_dict.values())
    filter_function = generate_filter_functions(config_dict, grammar_dict)
    samples = AllPairs(config_vals, filter_func=filter_function)
    samples = [OrderedDict(zip(config_dict.keys(), sample)) for sample in samples]

    cli_args = [option_to_cli(sample, grammar_dict) for sample in samples]

    # append overrides (if any)
    # grammar_override is a list (possibly empty). keep behavior similar to original.
    cli_args = [sample + grammar_override for sample in cli_args]
    return cli_args


def generate_cli_string(grammar: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> List[str]:
    """
    Generate CLI arguments as a single string per configuration.
    """
    return [" ".join(cli_args) for cli_args in generate_cli_args(grammar, config)]


def request_configurations(grammar_file):
    """Main function that replicates the original script behavior."""
    grammar = load_grammar(grammar_file)
    cli_string = generate_cli_string(grammar)
    return cli_string


def main():

    grammar_file = "/data/tahmeed/FuzzBenchPlusPlus/benchmarks/libxml2_xmllint/ct_grammar.json"
    cli_strings = request_configurations(grammar_file)
    for s in cli_strings:
        print(s)
        print()
        print()


if __name__ == "__main__":
    main()
