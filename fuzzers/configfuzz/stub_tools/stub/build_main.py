import json

from stub import grammar_utils
from stub.code_builder import CodeBuilder


def build_main(grammar: json):
    builder = CodeBuilder()
    file_op = '''
int main (int argc, char **argv) {
    char *input_file = argv[1];
    char filename[256];
    sprintf(filename, "/dev/shm/optfuzzer.%d", getpid());
    FILE *fp;
    if ((fp = fopen(input_file, "rb"))) {
        // get size of input data
        fseek(fp, 0L, SEEK_END);
        int size = ftell(fp);
        rewind(fp);
        // read data into array
        unsigned char input[size];
        fread(input, 1, size, fp);
        fclose(fp);
        // write data into in-mem file
        FILE *fp_mem;
        if ((fp_mem = fopen(filename, "wb"))) {
            fwrite(input, sizeof(input), 1, fp_mem);
            fclose(fp_mem);
        } else {
            printf("cannot create file %s\\n", filename);
            return 0;
        }

        argv[1] = filename;
        argv = configfuzz_get_args(&argc, argv);
    '''
    builder.write_block(file_op)
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

        remove(filename);
        return ret;
    }
    printf("cannot read file %s\\n", input_file);
    return 0;
}
        '''
    else:
        input_op = '''

        int ret = fuzz_main(argc, argv);
        remove(filename);
        return ret;
    }
    printf("cannot read file %s\\n", input_file);
    return 0;
}
        '''
    builder.write_block(input_op)
    print(builder.code())
