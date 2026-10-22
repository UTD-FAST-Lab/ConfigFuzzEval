import argparse
import json

from stub import build_stub, build_main, build_zero, build_printer


def parse_args():
    parser = argparse.ArgumentParser(description='Runs coverage experiments on ConfigFuzz empirical study and '
                                                 'summarize results.')
    parser.add_argument('-g',
                        '--grammar',
                        help='Path to the configuration grammar.',
                        required=True)
    parser.add_argument('-p',
                        '--printer',
                        help='Generate the printer instead of stub.',
                        action='store_true')
    return parser.parse_args()


def main():
    args = parse_args()
    with open(args.grammar, 'r') as f:
        grammar = json.load(f)
    if args.printer:
        print('''
#include <stdio.h>
#include <unistd.h>

        ''')
        build_stub.build_stub(grammar)
        build_printer.build_printer()
    else:
        assert 'maxcombs' in grammar
        max_combs = grammar['maxcombs']
        assert max_combs >= 0
        if max_combs == 0:
            build_zero.build_zero(grammar)
        else:
            build_stub.build_stub(grammar)
            build_main.build_main(grammar)


if __name__ == "__main__":
    main()
