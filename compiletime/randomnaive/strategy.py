import json
import random
from typing import Dict, List, Any


def load_grammar(grammar_file: str) -> Dict[str, Any]:
    with open(grammar_file, "r") as f:
        return json.load(f)


def generate_random_config(grammar: Dict[str, Any]) -> Dict[str, Any]:
    config = {}

    for opt in grammar["options"]:
        if opt["type"] == "bool":
            config[opt["name"]] = random.choice([True, False])
        elif opt["type"] == "enum":
            config[opt["name"]] = random.choice(opt["values"])
        elif opt["type"] == "depends":
            config[opt["name"]] = random.choice([True, False])
        elif opt["type"] == "str":
            config[opt["name"]] = "/usr"  # default string value
        else:
            config[opt["name"]] = None  # unknown type fallback

    return config


def generate_n_random_configs(grammar: Dict[str, Any], n: int = 10) -> List[Dict[str, Any]]:
    return [generate_random_config(grammar) for _ in range(n)]


def generate_cli_args(grammar: Dict[str, Any], config: Dict[str, Any]) -> List[str]:
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

    cli_args = []
    for opt in grammar["options"]:
        arg = option_to_cli(opt, config[opt["name"]])
        if arg:
            cli_args.append(arg)
    return cli_args


def request_configurations(grammar_file: str, n: int = 10) -> List[str]:
    grammar = load_grammar(grammar_file)
    configs = generate_n_random_configs(grammar, n)
    return [" ".join(generate_cli_args(grammar, config)) for config in configs]
