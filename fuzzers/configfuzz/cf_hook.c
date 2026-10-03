// Linked into every executable built with configfuzz-cc, which passes
// -Wl,--wrap=main so that the program's startup code calls __wrap_main instead of
// main. ConfigFuzz needs the program's main renamed (to fuzz_main) so its stub can
// run first; this does that without editing the benchmark sources.
//
// run.sh preloads the stub generated from the benchmark's rt_grammar.json, which
// defines configfuzz_entry. If it is not loaded (configure tests, helper programs,
// running the binary by hand), the program runs exactly as before.
#define _GNU_SOURCE
#include <dlfcn.h>

typedef int (*configfuzz_main_fn)(int, char **, char **);
typedef int (*configfuzz_entry_fn)(int, char **, configfuzz_main_fn);

int __real_main(int, char **, char **);

int __wrap_main(int argc, char **argv, char **envp) {
    configfuzz_entry_fn entry = (configfuzz_entry_fn)dlsym(RTLD_DEFAULT, "configfuzz_entry");
    if (entry)
        return entry(argc, argv, __real_main);
    return __real_main(argc, argv, envp);
}
