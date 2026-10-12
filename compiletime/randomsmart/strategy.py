
import json
import random
from typing import Dict, Any, List, Optional
import sys
from itertools import product


def load_grammar(grammar_file: str) -> Dict[str, Any]:
    with open(grammar_file, "r") as f:
        return json.load(f)


def set_option(config: Dict[str, Any], name: str, value: Any) -> None:
    config[name] = value


def apply_implies(config: Dict[str, Any], grammar: Dict[str, Any], opt: Dict[str, Any]) -> None:
    if "implies" not in opt:
        return
    for imp in opt["implies"]:
        if "=" in imp:
            iname, ival = imp.split("=", 1)
            iname = iname.strip()
            ival = ival.strip().lower()
            # Handle string to bool conversion
            if ival == "true":
                ival = True
            elif ival == "false":
                ival = False
            else:
                try:
                    # handle implied values like --with-sysroot=/path
                    implied_opt = get_option(grammar, iname)
                    if implied_opt["type"] == "str":
                        ival = ival  # keep as string
                    elif implied_opt["type"] == "enum" and ival in implied_opt["values"]:
                        ival = ival
                    else:
                        ival = False  # fallback
                except StopIteration:
                    print(f"Warning: implied option '{iname}' not found in grammar")
                    continue
        else:
            iname = imp.strip()
            ival = True
        try:
            implied_opt = get_option(grammar, iname)
            config[iname] = ival
            apply_implies(config, grammar, implied_opt)
        except StopIteration:
            print(f"Warning: implied option '{iname}' not found in grammar")
            continue


def check_conflicts(config: Dict[str, Any], opt: Dict[str, Any], value: Any) -> bool:
    if not value or "conflicts" not in opt:
        return False
    for conflict in opt["conflicts"]:
        if config.get(conflict, False):
            return True
    return False


def check_requires(config: Dict[str, Any], opt: Dict[str, Any], value: Any) -> bool:
    if not value or "requires" not in opt:
        return True
    for req in opt["requires"]:
        if not config.get(req, False):
            return False
    return True

def substitute_placeholders(expr: str, values: dict) -> str:
    """
    Replace placeholders in the string with values from the dictionary
    so the result can be passed to eval.

    Example:
        expr = "a + b * c"
        values = {"a": 2, "b": 3, "c": 4}
        result = substitute_placeholders(expr, values)
        # result -> "2 + 3 * 4"
    """
    for key, val in values.items():
        # Ensure proper Python representation (e.g., strings quoted)
        expr = expr.replace(key, repr(val))
    return expr

def check_meta_constraints(config, grammar):
    """
    Validate `config` against meta-constraints in `grammar`.

    Returns:
      True if valid, otherwise returns False after printing an error message.
    """
    meta_constraints = grammar.get("meta_constraints", [])
    for expr in meta_constraints:
        if not expr:
            continue
        try:
            # Substitute option names with their values in the config
            eval_expr = substitute_placeholders(expr, config)
            if not eval(eval_expr):
                print(f"Error: meta-constraint violation: {expr} evaluated to False with config {config}")
                return False
        except Exception as e:
            print(f"Error evaluating meta-constraint '{expr}': {e}")
            return False
    return True

def check_valid_config(config, grammar):
    """
    Validate `config` against pairwise constraints in `grammar`.

    Returns:
      True if valid, otherwise returns False after printing an error message.
    """
    # Build quick lookup: option_name -> list of pairwise constraints
    option_constraints = {}
    for opt in grammar.get("options", []):
        name = opt.get("name")
        if not name:
            continue
        pwc = opt.get("pairwise_constraints") or []
        if pwc:
            option_constraints[name] = pwc

    # Only consider options that both appear in config and have constraints
    for opt_name, constraints in option_constraints.items():
        if opt_name not in config:
            continue  # if the option isn't set, its constraints don't fire
        opt_value = config[opt_name]

        for constraint in constraints:
            # Each constraint should be [trigger_value, [[other_option, required_value], ...]]
            if not (isinstance(constraint, (list, tuple)) and len(constraint) == 2):
                # print(f"Error: malformed constraint for option '{opt_name}': {constraint}")
                return False

            trigger_value, required_pairs = constraint

            # Only enforce this constraint when the option's value matches the trigger
            if opt_value == trigger_value:
                if not isinstance(required_pairs, (list, tuple)):
                    # print(f"Error: required pairs for option '{opt_name}' must be a list/tuple, got {type(required_pairs)}")
                    return False
                for req in required_pairs:
                    if not (isinstance(req, (list, tuple)) and len(req) == 2):
                        # print(f"Error: malformed required pair in constraint for '{opt_name}': {req}")
                        return False
                    req_key, req_val = req
                    if config.get(req_key, object()) != req_val:
                        # print(f"Error: constraint violation for '{opt_name}={opt_value}'. "
                            #   f"Expected {req_key}={req_val} in config, but got {config.get(req_key)}")
                        return False

    return True




def get_option(grammar: Dict[str, Any], name: str) -> Dict[str, Any]:
    return next(opt for opt in grammar["options"] if opt["name"] == name)


# def generate_valid_random_config(grammar: Dict[str, Any]) -> Dict[str, Any]:
#     config = {}
#     true_count = 0

#     # Randomize order for variation
#     options = grammar["options"].copy()
#     random.shuffle(options)

#     for opt in options:
#         name = opt["name"]
#         if name in config:
#             continue

#         if opt["type"] == "bool":
#             val = random.choice([True, False])
#             if val and (check_conflicts(config, opt, val) or not check_requires(config, opt, val)):
#                 val = False
#             set_option(config, name, val)
#             if val:
#                 apply_implies(config, grammar, opt)

#         elif opt["type"] == "enum":
#             val = random.choice(opt["values"])
#             set_option(config, name, val)

#         elif opt["type"] == "depends":
#             val = random.choice([True, False])
#             if val and (check_conflicts(config, opt, val) or not check_requires(config, opt, val)):
#                 val = False
#             set_option(config, name, val)

#         elif opt["type"] == "str":
#             set_option(config, name, "/usr")

#         else:
#             config[name] = None

#     return config

def generate_random_config(grammar: Dict[str, Any], rng: random.Random) -> Dict[str, Any]:
    config = {}

    for opt in grammar["options"]:
        if opt["type"] == "bool":
            config[opt["name"]] = rng.choice([True, False])
        elif opt["type"] == "enum":
            config[opt["name"]] = rng.choice(opt["values"])
        elif opt["type"] == "depends":
            config[opt["name"]] = rng.choice([True, False])
        elif opt["type"] == "str":
            config[opt["name"]] = "/usr"  # default string value
        elif opt["type"] == "choice":  # current grammar format
            config[opt["name"]] = rng.choice(opt["choices"])
        else:
            config[opt["name"]] = None  # unknown type fallback

    return config


# --- Current grammar format -------------------------------------------------
# Options have type bool/choice and "cli" is a prefix ("enable"/"with"); rules are in
# a top-level "constraints" list. Flags are formatted like compiletime/maximum and
# constraints are interpreted like compiletime/pairwise.

def is_prefix_cli(opt: Dict[str, Any]) -> bool:
    return opt.get("cli", "enable") in ("enable", "with")


def constraint_holds(config: Dict[str, Any], grammar: Dict[str, Any], rule: Dict[str, Any]) -> bool:
    """Whether one condition {"opt", "val", optional "choice": "=="/"!="} holds."""
    opt = next((o for o in grammar["options"] if o["name"] == rule["opt"]), None)
    if opt is None:
        return True  # rule about an option that is not in the grammar
    val, op, cur = rule.get("val"), rule.get("choice"), config.get(rule["opt"])
    if opt["type"] == "bool":
        return (cur is True) == (val is True)
    if op is None and isinstance(val, bool):
        return val  # presence check: a choice option is always set
    same = str(cur) == str(val)
    return not same if op == "!=" else same


def check_grammar_constraints(config: Dict[str, Any], grammar: Dict[str, Any]) -> bool:
    for rule in grammar.get("constraints", []):
        if not constraint_holds(config, grammar, rule):
            continue
        for then in rule.get("then", []):
            if "or" in then:
                if not any(constraint_holds(config, grammar, alt) for alt in then["or"]):
                    return False
            elif not constraint_holds(config, grammar, then):
                return False
    return True


def generate_n_valid_random_configs(grammar: Dict[str, Any], n: int = 10,
                                    rng: Optional[random.Random] = None) -> List[Dict[str, Any]]:
    rng = rng or random.Random()
    VERY_LARGE_LIMIT = 10000
    random_valid_configs = []
    for i in range(VERY_LARGE_LIMIT):
        config = generate_random_config(grammar, rng)
        if check_valid_config(config, grammar) and check_meta_constraints(config, grammar) \
                and check_grammar_constraints(config, grammar):
            random_valid_configs.append(config)
            if len(random_valid_configs) >= n:
                break
    return random_valid_configs


def option_to_cli(opt: Dict[str, Any], val: Any) -> str:
    if is_prefix_cli(opt):  # current grammar format, formatted like compiletime/maximum
        style, name = opt.get("cli", "enable"), opt["name"]
        if isinstance(val, bool):
            return f"--{style}-{name}" if val else f"--{'disable' if style == 'enable' else 'without'}-{name}"
        return f"--{style}-{name}={val}" if val not in (None, "") else ""
    if opt["type"] == "bool":
        if val:
            return opt["cli"]
        else:
            if opt["cli"].startswith("--with-"):
                return "--without-" + opt["cli"][7:]
            elif opt["cli"].startswith("--enable-"):
                return "--disable-" + opt["cli"][9:]
    elif opt["type"] == "enum":
        return f'{opt["cli"]}={val}'
    elif opt["type"] == "depends":
        if val is True:
            return opt["cli"]
        elif val is False:
            return "--without-" + opt["cli"][7:]
        else:
            return f'{opt["cli"]}={val}'
    elif opt["type"] == "str":
        return f'{opt["cli"]}={val}'
    return ""


def request_configurations(grammar_file: str, n: int = 10,
                           random_seed: int = None) -> List[str]:
    grammar = load_grammar(grammar_file)

    # A private generator: the same random_seed gives the same configurations,
    # without changing Python's global random state for other strategies
    configs = generate_n_valid_random_configs(grammar, n, random.Random(random_seed))
    cli_lines = []
    for config in configs:
        cli_args = []
        for opt in grammar["options"]:
            arg = option_to_cli(opt, config.get(opt["name"]))
            if arg:
                cli_args.append(arg)
        cli_lines.append(" ".join(cli_args))
    return cli_lines
    


if __name__ == "__main__":

    grammar_file = sys.argv[1]
    grammar = load_grammar(grammar_file)
    configurations = generate_n_valid_random_configs(grammar,100)
    print()
    print()
    for config in configurations:
        temp = {k: v for k, v in config.items() if k in ['pcre2-8','pcre2-16','pcre2-32']}
        count_True = len(list(filter(lambda x: x==True,list(temp.values()))))
        print("-"*50)
        print("Config:")
        print(config)
        print(temp," True count:",count_True," Valid:",check_valid_config(config,grammar))
        print("-"*50)
        print()



    # config_parameters = {
    #     'pcre2-8': [True, False],
    #     'pcre2-16': [True, False],
    #     'pcre2-32': [True, False],
    # }

    # # Generate all possible combinations of configs
    # keys = list(config_parameters.keys())
    # values = list(config_parameters.values())
    # all_combinations = [dict(zip(keys, combination)) for combination in product(*values)]

    # # Print combinations as tuples
    # for combination in all_combinations:
    #     combo =tuple(combination.items())
    #     config = dict(combo)
    #     for opt in keys:
    #         val = config[opt]
    #         del config[opt]

    #         option = next((item for item in grammar["options"] if item["name"] == opt), None)

    #         print("Option:", opt, "Value:", val, "Current Config:", config)
    #         print("Conflict:",check_conflicts(config,option, val))
    #         print()
    #         config[opt] = val




