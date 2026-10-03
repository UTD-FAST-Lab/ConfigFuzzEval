ARG parent_image
FROM $parent_image

# ConfigFuzz (Zhang et al., "Fuzzing Configurations of Program Options", TOSEM 2023)
# encodes command-line options in the first bytes of each input, so AFL++ fuzzes
# options and file contents together. Its stub generator (stub_tools/) is taken
# unchanged from the paper's artifact: https://doi.org/10.6084/m9.figshare.20792062
# (CC BY 4.0). The fuzzer is the same AFL++ build as fuzzers/aflplusplus.

RUN apt-get update && \
    apt-get install -y \
        build-essential \
        python3-dev \
        python3-setuptools \
        automake \
        cmake \
        git \
        flex \
        bison \
        libglib2.0-dev \
        libpixman-1-dev \
        cargo \
        libgtk-3-dev \
        # for QEMU mode
        ninja-build \
        gcc-$(gcc --version|head -n1|sed 's/\..*//'|sed 's/.* //')-plugin-dev \
        libstdc++-$(gcc --version|head -n1|sed 's/\..*//'|sed 's/.* //')-dev

# Download afl++.
RUN git clone -b dev https://github.com/AFLplusplus/AFLplusplus /configfuzz/afl && \
    cd /configfuzz/afl && \
    git checkout 56d5aa3101945e81519a3fac8783d0d8fad82779 || \
    true

# Build without Python support as we don't need it.
# Set AFL_NO_X86 to skip flaky tests.
RUN cd /configfuzz/afl && \
    unset CFLAGS CXXFLAGS && \
    export CC=clang AFL_NO_X86=1 && \
    PYTHON_INCLUDE=/ make

# ConfigFuzz: main hook, compiler wrapper and stub generator.
COPY cf_hook.c configfuzz-cc make_stub.py run.sh coverage.py /configfuzz/
COPY stub_tools /configfuzz/stub_tools
RUN cd /configfuzz && \
    clang -O2 -fPIC -c cf_hook.c -o cf_hook.o && \
    ln -s configfuzz-cc configfuzz-c++ && \
    chmod +x configfuzz-cc run.sh

# GENERAL
ENV FUZZER_COMP=/configfuzz/configfuzz-cc
ENV FUZZER_COMPXX=/configfuzz/configfuzz-c++

CMD ["bash", "-c", "cp -r /configfuzz /fuzzer_output/"]
