# Crash triage with afl-collect (afl-utils); see collect.py. Built from bug-triaging/.
FROM fbpp/base

RUN apt-get update && apt-get install -y gdb git && rm -rf /var/lib/apt/lists/*

# afl-utils at a fixed commit (it installs its own copy of the exploitable gdb plugin).
ARG AFL_UTILS_COMMIT=73f498c14f91762734433d4657e8ca4bc0a90c7d
RUN git clone https://github.com/rc0r/afl-utils.git /afl-utils && \
    git -C /afl-utils checkout $AFL_UTILS_COMMIT && \
    cd /afl-utils && python3 setup.py install

# That exploitable (1.32-rcor) reads gdb 12's quoted architecture name ("i386:x86-64") with
# its quotes and stops classifying; use upstream exploitable's pattern, which strips them.
RUN F=$(python3 -c "import exploitable, os; print(os.path.join(exploitable.__path__[0], 'lib/gdb_wrapper/x86.py'))") && \
    sed -i 's|_re_gdb_arch = re.compile(r"\\(\\w+\\s+(.+)\\)")|_re_gdb_arch = re.compile(r"\\(\\w+\\s+\\"*(.+?)\\"*\\)")|' $F && \
    grep -q 'w+\\s+\\"\*(.+?)' $F

COPY crash_commands.py afl-collect/launcher.py afl-collect/collect.py /triage/
COPY afl-collect/smoke_test.sh /smoke_test.sh

CMD ["python3", "/triage/collect.py"]
