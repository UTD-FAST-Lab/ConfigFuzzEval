import json

from stub import grammar_utils
from stub.code_builder import CodeBuilder


def build_zero(grammar: json):
    builder = CodeBuilder()
    builder.write_line('int main (int argc, char **argv) {', indent=0)
    builder.write_line('char *filename = argv[1];', indent=1)
    cmdline = grammar_utils.cmd_line(grammar)
    fixed_args_num = len([c for c in cmdline if c != '$inopts' and c != '$STDIN' and c != '$INPUTFILE'])
    builder.write_line(f'static char *cmdargs[{fixed_args_num + 3}];', indent=1)
    argspos = 0
    builder.write_line(f'cmdargs[{argspos}] = argv[0];', indent=1)
    argspos += 1
    for arg in cmdline:
        if arg == '$inopts' or arg == '$STDIN':
            continue
        elif arg == '$INPUTFILE':
            builder.write_line(f'cmdargs[{argspos}] = filename;', 1)
        else:
            builder.write_line(f'cmdargs[{argspos}] = "{arg}";', 1)
        argspos += 1
    builder.write_line(f'cmdargs[{argspos}] = NULL;', indent=1)
    builder.write_line(f'argv = cmdargs;', indent=1)
    builder.write_line(f'argc = {argspos};', indent=1)

    if '$STDIN' in grammar_utils.cmd_line(grammar):
        input_op = '''
    int oldstdin = dup(fileno(stdin));
    fpos_t pos;
    fflush(stdin);
    fgetpos(stdin, &pos);
    freopen(filename, "r", stdin);

    int ret = fuzz_main(argc, argv);

    fflush(stdin);
    dup2(oldstdin,fileno(stdin));
    close(oldstdin);
    clearerr(stdin);
    fsetpos(stdout, &pos);

    return ret;
}
            '''
    else:
        input_op = '''
        
    int ret = fuzz_main(argc, argv);
    return ret;
}
            '''
    builder.write_block(input_op)
    print(builder.code())
