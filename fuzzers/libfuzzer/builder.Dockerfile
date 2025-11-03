ARG parent_image
FROM ${parent_image}

RUN apt-get update -qq && apt-get -y install clang llvm build-essential

RUN mkdir /libfuzzer

COPY run.sh /libfuzzer/
COPY coverage.py /libfuzzer/


ENV FUZZER_COMP=clang
ENV FUZZER_COMPXX=clang++
ENV FUZZER_FLAGS="-fsanitize=fuzzer,address"
ENV CFLAGS="-fprofile-instr-generate -fcoverage-mapping"
ENV CXXFLAGS="-fprofile-instr-generate -fcoverage-mapping"
ENV CC=clang-18
ENV CXX=clang++-18

CMD ["bash", "-c", "cp -r /libfuzzer /fuzzer_output/ && cp /libfuzzer/run.sh /fuzzer_output/ && cp /libfuzzer/coverage.py /fuzzer_output/"]