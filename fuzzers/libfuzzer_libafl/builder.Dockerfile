ARG parent_image
FROM $parent_image


# Install any remaining dependencies required for libpng + LibAFL example
RUN apt-get update -qq && apt-get install -y --no-install-recommends \
    clang-14 llvm-14 autoconf libtool automake zlib1g zlib1g-dev jq && \
    rm -rf /var/lib/apt/lists/*
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"
RUN rustup toolchain install nightly && rustup default nightly
         
ENV CC=clang-18
ENV CXX=clang++-18
 
# setup  LibAFL 
RUN git clone https://github.com/AFLplusplus/LibAFL.git /libfuzzer_libafl
WORKDIR /libfuzzer_libafl
RUN  cargo build --release
WORKDIR /libfuzzer_libafl/fuzzers/inprocess/libfuzzer_libpng
RUN cargo build --release
RUN ls -l /libfuzzer_libafl/fuzzers/inprocess/libfuzzer_libpng/target/release/libafl_cc
 
 
ENV FUZZER_COMP=/libfuzzer_libafl/fuzzers/inprocess/libfuzzer_libpng/target/release/libafl_cc
ENV FUZZER_COMPXX=/libfuzzer_libafl/fuzzers/inprocess/libfuzzer_libpng/target/release/libafl_cxx
ENV FUZZER_FLAGS="-lz -lm"
ENV CC=clang-18
ENV CXX=clang++-18


COPY run.sh /libfuzzer_libafl/
COPY coverage.py /libfuzzer_libafl/

CMD ["bash", "-c", "cp -r /libfuzzer_libafl /fuzzer_output/", "&&", "cp /libfuzzer_libafl/run.sh /fuzzer_output/ ", "&&", "cp /libfuzzer_libafl/coverage.py /fuzzer_output/"]