ARG parent_image
FROM $parent_image

WORKDIR /

# ProphetFuzz's fuzzer is the CarpetFuzz-fuzzer repo (an AFL++ fork with -K
# option-combination support), pinned by ProphetFuzz as a git submodule at 4e07d2a.
# It is built with LLVM 12, as in ProphetFuzz's own Docker image.
RUN apt-get update && \
    apt-get install -y \
        clang-12 \
        libclang-12-dev \
        lld-12 \
        llvm-12 \
        llvm-12-dev \
        llvm-12-runtime \
        llvm-12-tools

RUN git clone https://github.com/waugustus/CarpetFuzz-fuzzer /prophetfuzz && \
    cd /prophetfuzz && \
    git checkout 4e07d2a16c058f298af86fb9f10c3e5135f0acec

WORKDIR /prophetfuzz

RUN make CC=clang-12 LLVM_CONFIG=llvm-config-12

# GENERAL
ENV FUZZER_COMP=/prophetfuzz/afl-clang-fast
ENV FUZZER_COMPXX=/prophetfuzz/afl-clang-fast++
COPY run.sh /prophetfuzz
COPY coverage.py /prophetfuzz
RUN chmod +x /prophetfuzz/run.sh

CMD ["bash", "-c", "cp -r /prophetfuzz /fuzzer_output/"]
