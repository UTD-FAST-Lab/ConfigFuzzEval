import json

with open("grammar.json", "r") as f:
    grammar = json.load(f)

# Helper functions for relationships
def get_option(name):
    return next(opt for opt in grammar["options"] if opt["name"] == name)

def set_option(config, name, value):
    config[name] = value

def apply_implies(config, opt):
    if "implies" in opt:
        for imp in opt["implies"]:
            # Format: "option" or "option=value"
            if "=" in imp:
                iname, ival = imp.split("=")
                ival = ival.strip().lower() == "true"
            else:
                iname, ival = imp, True
            set_option(config, iname.strip(), ival)

def check_conflicts(config, opt, value):
    # Return True if enabling opt with value would conflict with existing config
    if not value or "conflicts" not in opt:
        return False
    for conflict in opt["conflicts"]:
        if config.get(conflict) is True:
            return True
    return False

def check_requires(config, opt, value):
    if not value or "requires" not in opt:
        return True
    for req in opt["requires"]:
        if not config.get(req, False):
            return False
    return True

# Generate "all enabled" config
config = {}

# First, set all options to enabled if possible, except where conflicts/requires apply
for opt in grammar["options"]:
    # Skip options with "minimum" or that are only valid if another is off
    if opt["name"] == "minimum":
        set_option(config, opt["name"], False)
        continue
    # Set enum to first value (often "aix" for aix_soname) or True for bools
    if opt["type"] == "bool":
        # Check conflicts
        if check_conflicts(config, opt, True):
            set_option(config, opt["name"], False)
            continue
        # Check requires
        if not check_requires(config, opt, True):
            set_option(config, opt["name"], False)
            continue
        set_option(config, opt["name"], True)
    elif opt["type"] == "enum":
        set_option(config, opt["name"], opt["values"][0])
    elif opt["type"] == "depends":
        set_option(config, opt["name"], True)
    elif opt["type"] == "str":
        set_option(config, opt["name"], "/usr")
    # Apply implied relationships
    apply_implies(config, opt)

# Re-evaluate conflicts (set conflicting options to False)
for opt in grammar["options"]:
    if "conflicts" in opt and config.get(opt["name"], False):
        for conflict in opt["conflicts"]:
            if config.get(conflict, False):
                # Prefer enabling current, disable conflicting
                config[conflict] = False

# Re-evaluate requires: if requires are not met, disable option
for opt in grammar["options"]:
    if "requires" in opt and config.get(opt["name"], False):
        for req in opt["requires"]:
            if not config.get(req, False):
                config[opt["name"]] = False

# Print configuration as CLI arguments (for use with ./configure)
def option_to_cli(opt, val):
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
    cli_args.append(option_to_cli(opt, config[opt["name"]]))

print(" ".join(arg for arg in cli_args if arg))
