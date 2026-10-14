# Copyright 2016 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
################################################################################

ARG parent_image
FROM $parent_image

# GENERAL
ARG CC=$FUZZER_COMP
ARG CXX=$FUZZER_COMPXX
ARG CFLAGS=""

# GENERAL
# CC and CXX are set to clang-18 and clang++-18 wheb building coverage bianries
# If this needs to be changed, update the Dockerfile accordingly.

RUN apt-get update && apt-get install -y --no-install-recommends \
        make autoconf libtool pkg-config \
        zlib1g-dev liblzma-dev libbsd-dev

# Build requires automake 1.16.3
RUN curl -LO http://mirrors.kernel.org/ubuntu/pool/main/a/automake-1.16/automake_1.16.5-1.3_all.deb && \
    apt install ./automake_1.16.5-1.3_all.deb
RUN git clone --depth 1 https://github.com/libexpat/libexpat.git /libexpat
WORKDIR /libexpat/expat
COPY build.sh .

RUN bash build.sh

# GENERAL
# Copy supporting files to the docker image
COPY run_target.sh /
COPY seed /seed
COPY dict /
COPY ranked_stubs.txt /
COPY build.sh /
COPY rt_grammar.json /
# CarpetFuzz/ProphetFuzz inputs: the target's man page and CarpetFuzz's
# analysis of it (fuzzers/carpetfuzz/analysis/generate.sh).
COPY manpage.1 /
COPY carpetfuzz /carpetfuzz_analysis
COPY load_src.sh /
# Copy the binary to fuzz
CMD ["bash", "-c", "cp -r /libexpat/expat/xmlwf/xmlwf /benchmark_out_dir/       && cp /rt_grammar.json /benchmark_out_dir/ && cp /manpage.1 /benchmark_out_dir/ && cp -r /carpetfuzz_analysis /benchmark_out_dir/carpetfuzz  &&  cp /build.sh /benchmark_out_dir/  && cp /ranked_stubs.txt /benchmark_out_dir/  &&  cp /dict /benchmark_out_dir/  &&  cp /run_target.sh /benchmark_out_dir/ && cp -r /seed /benchmark_out_dir/seed && cp /load_src.sh /benchmark_out_dir/"]

