ARG parent_image
FROM $parent_image

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
RUN apt-get update && \
    apt-get install -y  libinih-dev libcurl4-openssl-dev xmlto libpng-dev gawk vim nano htop autoconf automake build-essential libtool cmake git sudo software-properties-common gperf libselinux1-dev  bison texinfo flex zlib1g-dev libexpat1-dev libmpg123-dev wget curl python3-pip unzip pkg-config clang llvm-dev python3.11-dev &&\
    python3 -m pip install -U pip

RUN (apt update && apt install -y clang-15 llvm-15-dev libjson-c-dev libgsl-dev )
RUN (python3.11 -m pip install z3-solver numpy scikit-learn)
RUN sudo apt install -y gettext libgpgmepp-dev libfontconfig-dev libfreetype-dev   libjpeg-dev ninja-build libopenjp2-7 libopenjp2-7-dev  libopenjp2-tools libnss3-dev libboost-dev libboost-all-dev  libboost-dev clang-format

# setup VAFuzz
ARG CACHEBUST=1
RUN git clone https://github.com/UTD-FAST-Lab/VAFuzz /vafuzz


# Build without Python support as we don't need it.
# Set AFL_NO_X86 to skip flaky tests.
# VAFuzz is based on AFL++ 4.09a, whose LLVM passes do not compile against the
# base image's LLVM 18 (and afl-cc passes -fexperimental-new-pass-manager,
# which clang 18 rejects), so build it against LLVM 15 instead.
# vafuzz.patch:
#  - links afl-fuzz against python3.10, which (unlike python3.11) exists in
#    the fbpp/runner image;
#  - fixes crashes in the z3 solver generator and its config generation
#    (generated scripts that did not parse, option names that are not Python
#    identifiers, non-Boolean constraints, exit(1) on a short queue, KMeans
#    on a single trace);
#  - fixes the target runtime crashing on an empty options file (config.seed);
#  - fixes heap corruption in argv_havoc (resizing mutations on the fixed-size
#    options bitmap, and clobbering the interrupted stage's counters).
COPY vafuzz.patch /tmp/vafuzz.patch
RUN cd /vafuzz && git checkout f222b77a769100b2d86c9c20ef1f1858b76d5523 && \
    git apply /tmp/vafuzz.patch && \
    unset CFLAGS CXXFLAGS && \
    export CC=clang-15 CXX=clang++-15 LLVM_CONFIG=llvm-config-15 AFL_NO_X86=1 && \
    PYTHON_INCLUDE=/ make

# afl-fuzz runs inside fbpp/runner with only /vafuzz mounted, so ship what it
# needs at runtime that the runner lacks: the GSL libraries (found through an
# $ORIGIN rpath) and the Python packages the z3 solver imports.
RUN apt-get install -y patchelf && \
    mkdir -p /vafuzz/lib && \
    cp -L /usr/lib/x86_64-linux-gnu/libgsl.so.27 \
          /usr/lib/x86_64-linux-gnu/libgslcblas.so.0 \
          /usr/lib/x86_64-linux-gnu/libjson-c.so.5 /vafuzz/lib/ && \
    patchelf --set-rpath '$ORIGIN/lib' /vafuzz/afl-fuzz && \
    python3 -m pip install --no-cache-dir --target /vafuzz/pydeps \
        z3-solver numpy scikit-learn

# GENERAL
ENV FUZZER_COMP=/vafuzz/afl-clang-fast
ENV FUZZER_COMPXX=/vafuzz/afl-clang-fast++
COPY run.sh /vafuzz
COPY coverage.py /vafuzz

CMD ["bash", "-c", "cp -r /vafuzz /fuzzer_output/", "&&", "cp /vafuzz/run.sh /fuzzer_output/ ", "&&", "cp /vafuzz/coverage.py /fuzzer_output/"]