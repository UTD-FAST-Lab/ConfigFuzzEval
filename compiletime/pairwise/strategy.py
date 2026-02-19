# LLM Generated

import json
import sys
import itertools
import random
from z3 import *

class PairwiseGenerator:
    def __init__(self, grammar_file):
        self.solver = Solver()
        self.z3_vars = {}
        self.options = []
        self.option_map = {}  # Map name -> option dict
        self.choice_maps = {} # Map name -> {val: index, index: val} for choice types
        
        self.load_grammar(grammar_file)
        self.build_z3_model()

    def load_grammar(self, grammar_file):
        with open(grammar_file, 'r') as f:
            data = json.load(f)
            
        # Filter out "removed" options if they exist in the list but are marked removed
        # (The JSON provided puts removed items in a separate list, so we just use 'options')
        self.options = data.get('options', [])
        self.constraints = data.get('constraints', [])
        
        for opt in self.options:
            self.option_map[opt['name']] = opt
            
            # Pre-process 'choice' types to integers for Z3
            if opt['type'] == 'choice':
                choices = opt.get('choices', [])
                # Map logical values to 0..N-1
                forward = {val: i for i, val in enumerate(choices)}
                backward = {i: val for i, val in enumerate(choices)}
                self.choice_maps[opt['name']] = (forward, backward)

    def build_z3_model(self):
        # 1. Define Variables
        for opt in self.options:
            name = opt['name']
            if opt['type'] == 'bool':
                self.z3_vars[name] = Bool(name)
            elif opt['type'] == 'choice':
                self.z3_vars[name] = Int(name)
                # Constraint: Choice must be within index range
                count = len(opt['choices'])
                self.solver.add(self.z3_vars[name] >= 0)
                self.solver.add(self.z3_vars[name] < count)

        # 2. specific 'constraints' block
        for constr in self.constraints:
            self.add_json_constraint(constr)

    def add_json_constraint(self, constr):
        """Translates JSON constraint objects into Z3 logical implications."""
        try:
            # Build the Trigger Expression (IF part)
            trigger_expr = self.get_z3_expr(constr['opt'], constr['val'], constr.get('choice'))
            
            # Build the Effect Expression (THEN part)
            # The JSON uses a list of effects
            effects = []
            for eff in constr['then']:
                # Case OR: at least one of the listed sub-effects must hold
                if 'or' in eff:
                    or_exprs = [
                        self.get_z3_expr(branch['opt'], branch['val'], branch.get('choice'))
                        for branch in eff['or']
                    ]
                    effects.append(Or(*or_exprs))
                else:
                    effects.append(self.get_z3_expr(eff['opt'], eff['val'], eff.get('choice')))
            
            if effects:
                # Logic: Trigger implies (Effect1 AND Effect2 ...)
                self.solver.add(Implies(trigger_expr, And(*effects)))
                
        except KeyError as e:
            print(f"Warning: Skipping constraint due to missing option: {e}")

    def get_z3_expr(self, opt_name, val, choice_op=None):
        """Helper to create z3 expression (Var == Val)."""
        z3_var = self.z3_vars[opt_name]
        opt_type = self.option_map[opt_name]['type']
        
        if opt_type == 'bool':
            # Handle standard boolean flags
            if val is True: return z3_var
            else: return Not(z3_var)
            
        elif opt_type == 'choice':
            # --- Handle "Presence" Checks (val: true/false, no specific string value) ---
            if choice_op is None and isinstance(val, bool):
                if val is True:
                    # The constraint checks if the option is "present" (set to anything).
                    # Since your choice list doesn't have a "None" or "False" option,
                    # the option is ALWAYS set. Therefore, this condition is always True.
                    return True 
                else:
                    # Checks if the option is NOT present.
                    # Since it's always set to something in this grammar, this is always False.
                    return False
            # -------------------------------------

            # Handle specific value checks with choice operator (e.g., choice: "==", val: "/usr/include")
            forward_map = self.choice_maps[opt_name][0]
            
            # Type correction: constraints might use int, grammar uses string, or vice versa
            lookup_val = val
            if val not in forward_map:
                if str(val) in forward_map: lookup_val = str(val)
                elif int(val) in forward_map: lookup_val = int(val)
            
            if lookup_val in forward_map:
                idx = forward_map[lookup_val]
                if choice_op == "!=":
                    return z3_var != idx
                else:  # "==" or default
                    return z3_var == idx
            else:
                # Value not found in grammar? Treat as impossible condition.
                return False
            
        return True

    def get_all_valid_pairs(self):
        """Generates all pairwise combinations (2-way) that are logically possible."""
        print("Generating valid pairs...")
        pairs = set()
        
        # Get list of (OptionName, Value) tuples for every option
        domain_values = {} 
        for opt in self.options:
            name = opt['name']
            if opt['type'] == 'bool':
                domain_values[name] = [True, False]
            elif opt['type'] == 'choice':
                domain_values[name] = opt['choices'] # Raw values

        opt_names = [o['name'] for o in self.options]
        
        # Iterate over every unique pair of parameters
        for i in range(len(opt_names)):
            for j in range(i + 1, len(opt_names)):
                p1, p2 = opt_names[i], opt_names[j]
                
                # Cartesian product of their domains
                for v1 in domain_values[p1]:
                    for v2 in domain_values[p2]:
                        # Check if this pair is valid in Z3
                        self.solver.push()
                        self.solver.add(self.get_z3_expr(p1, v1))
                        self.solver.add(self.get_z3_expr(p2, v2))
                        
                        if self.solver.check() == sat:
                            # Store as tuple of tuples: ((Opt1, Val1), (Opt2, Val2))
                            pairs.add(((p1, v1), (p2, v2)))
                        
                        self.solver.pop()
        
        print(f"Total valid pairs to cover: {len(pairs)}")
        return list(pairs)

    def generate(self):
        """The greedy IPOG-like generation loop."""
        required_pairs = self.get_all_valid_pairs()
        generated_configs = []
        
        while required_pairs:
            print(f"Remaining pairs: {len(required_pairs)}")
            
            # Start a new configuration
            self.solver.push()
            current_config = {}
            
            # Greedy Heuristic:
            # 1. Find the pair in 'required_pairs' that is hardest to satisfy? 
            #    Or just pick the first one to start the row.
            seed_pair = required_pairs[0]
            
            # Enforce the seed pair in solver
            (opt1, val1), (opt2, val2) = seed_pair
            self.solver.add(self.get_z3_expr(opt1, val1))
            self.solver.add(self.get_z3_expr(opt2, val2))
            current_config[opt1] = val1
            current_config[opt2] = val2
            
            # Fill the rest of the parameters
            # Shuffle order to add randomness to the greedy fill
            remaining_opts = [o['name'] for o in self.options if o['name'] not in current_config]
            random.shuffle(remaining_opts)
            
            for opt_name in remaining_opts:
                best_val = None
                best_score = -1
                
                # Try all values for this option
                candidates = []
                opt_type = self.option_map[opt_name]['type']
                if opt_type == 'bool': candidates = [True, False]
                else: candidates = self.option_map[opt_name]['choices']
                
                random.shuffle(candidates) # Randomized tie-breaking

                for val in candidates:
                    # Check consistency
                    self.solver.push()
                    self.solver.add(self.get_z3_expr(opt_name, val))
                    is_sat = self.solver.check() == sat
                    self.solver.pop()
                    
                    if is_sat:
                        # Calculate Score: How many new pairs does this add?
                        score = 0
                        # Check against already set items in this row
                        for existing_opt, existing_val in current_config.items():
                            # Order pair keys alphabetically or consistently to match required_pairs format
                            # My required_pairs format is loosely ((p1,v1), (p2,v2))
                            # We construct the candidate pair and check existence
                            
                            # Normalize order for lookup
                            if existing_opt < opt_name:
                                pair_check = ((existing_opt, existing_val), (opt_name, val))
                            else:
                                pair_check = ((opt_name, val), (existing_opt, existing_val))
                                
                            if pair_check in required_pairs:
                                score += 1
                        
                        if score > best_score:
                            best_score = score
                            best_val = val
                
                # Assign the winner
                if best_val is not None:
                    current_config[opt_name] = best_val
                    self.solver.add(self.get_z3_expr(opt_name, best_val))
                else:
                    # If no value is valid (should typically not happen if model is sound),
                    # we let Z3 fill it later or ignore.
                    pass

            # Row is complete. Save it.
            generated_configs.append(current_config)
            self.solver.pop() # Clear the specific constraints for this row
            
            # Remove covered pairs
            # We must verify exactly what this row covered
            pairs_to_remove = []
            for p_tuple in required_pairs:
                (o1, v1), (o2, v2) = p_tuple
                if current_config.get(o1) == v1 and current_config.get(o2) == v2:
                    pairs_to_remove.append(p_tuple)
            
            for p in pairs_to_remove:
                required_pairs.remove(p)
                
        return generated_configs

    def format_cli(self, config):
        """Converts a config dictionary to CLI arguments."""
        args = []
        for name, val in config.items():
            opt_def = self.option_map[name]
            cli_mode = opt_def.get('cli', 'enable') # default to enable/disable
            
            if opt_def['type'] == 'bool':
                if cli_mode == 'enable':
                    # e.g., --enable-foo or --disable-foo
                    prefix = "enable" if val else "disable"
                    args.append(f"--{prefix}-{name}")
                elif cli_mode == 'with':
                    # e.g. --with-foo or --without-foo
                    prefix = "with" if val else "without"
                    args.append(f"--{prefix}-{name}")
            else:
                # Choice / String types
                # usually --with-name=value
                if isinstance(val, bool):
                    # Handle "Presence" Checks for choice types
                    if val is True:
                        args.append(f"--{cli_mode}-{name}")
                    else:
                        args.append(f"--without-{name}")
                else:
                    args.append(f"--{cli_mode}-{name}={val}")
                
        return " ".join(args)


def request_configurations(grammar_file):
    gen = PairwiseGenerator(grammar_file)
    res = gen.generate()
    
    configs = []
    
    for conf in res:
        cli_args = gen.format_cli(conf)
        configs.append(cli_args)
    
    return configs


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python gen_pairwise.py <grammar.json>")
        sys.exit(1)
        
    grammar_path = sys.argv[1]
    
    gen = PairwiseGenerator(grammar_path)
    configs = gen.generate()
    
    print("\n" + "="*40)
    print(f"Generated {len(configs)} configurations to cover all valid pairs.")
    print("="*40 + "\n")
    
    for i, conf in enumerate(configs):
        print(f"Test Case #{i+1}:")
        print(f"  {gen.format_cli(conf)}")
        print("-" * 20)