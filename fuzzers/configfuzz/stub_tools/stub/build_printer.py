import json

from stub.code_builder import CodeBuilder


def build_printer(return_str: bool = False):
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
        for (int i = 0; i < argc; i++)
            printf("%s\\n", argv[i]);
        return 0;
    }
}
    '''
    builder.write_block(file_op)
    if return_str:
        return builder.code()
    else:
        print(builder.code())
