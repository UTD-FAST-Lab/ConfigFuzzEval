import json
import random
from typing import Dict, Any, List


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


def get_option(grammar: Dict[str, Any], name: str) -> Dict[str, Any]:
    return next(opt for opt in grammar["options"] if opt["name"] == name)


def generate_valid_random_config(grammar: Dict[str, Any]) -> Dict[str, Any]:
    config = {}

    # Randomize order for variation
    options = grammar["options"].copy()
    random.shuffle(options)

    for opt in options:
        name = opt["name"]
        if name in config:
            continue

        if opt["type"] == "bool":
            val = random.choice([True, False])
            if val and (check_conflicts(config, opt, val) or not check_requires(config, opt, val)):
                val = False
            set_option(config, name, val)
            if val:
                apply_implies(config, grammar, opt)

        elif opt["type"] == "enum":
            val = random.choice(opt["values"])
            set_option(config, name, val)

        elif opt["type"] == "depends":
            val = random.choice([True, False])
            if val and (check_conflicts(config, opt, val) or not check_requires(config, opt, val)):
                val = False
            set_option(config, name, val)

        elif opt["type"] == "str":
            set_option(config, name, "/usr")

        else:
            config[name] = None

    return config


def generate_n_valid_random_configs(grammar: Dict[str, Any], n: int = 10) -> List[Dict[str, Any]]:
    return [generate_valid_random_config(grammar) for _ in range(n)]


def option_to_cli(opt: Dict[str, Any], val: Any) -> str:
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


def request_configurations(grammar_file: str, n: int = 2) -> List[str]:
    grammar = load_grammar(grammar_file)
    configs = generate_n_valid_random_configs(grammar, n)
    cli_lines = []
    for config in configs:
        cli_args = []
        for opt in grammar["options"]:
            arg = option_to_cli(opt, config.get(opt["name"]))
            if arg:
                cli_args.append(arg)
        cli_lines.append(" ".join(cli_args))
    return cli_lines