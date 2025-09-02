ARG parent_image
FROM $parent_image

WORKDIR /

RUN apt-get update
RUN apt install -y \
    clang-12 \
    clang-tools-12 \
    clang-12-doc \
    libclang-common-12-dev \
    libclang-12-dev \
    libclang-cpp12-dev \
    lld-12 \
    lldb-12 \
    llvm-12 \
    llvm-12-dev \
    llvm-12-doc \
    llvm-12-runtime \
    llvm-12-tools \
    libomp-12-dev


RUN git clone https://github.com/waugustus/CarpetFuzz-fuzzer /carpetfuzz

WORKDIR /carpetfuzz

RUN make CC=clang-12 LLVM_CONFIG=llvm-config-12





# GENERAL
ENV FUZZER_COMP=/carpetfuzz/afl-clang-fast
ENV FUZZER_COMPXX=/carpetfuzz/afl-clang-fast++
COPY run.sh /carpetfuzz
COPY coverage.py /carpetfuzz
RUN chmod +x /carpetfuzz/run.sh
CMD ["bash", "-c", "cp -r /carpetfuzz /fuzzer_output/", "&&", "cp /carpetfuzz/run.sh /fuzzer_output/"]