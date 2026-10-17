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
WORKDIR /
RUN apt-get update && apt-get install -y make cmake flex bison
# The download below falls back to the copy in benchmarks/sources/ if it fails
# (the `sources` build context, passed by common/docker_image_builder.py).
COPY --from=sources bison-3.8.tar.xz /fbpp_sources/
RUN (wget --tries=3 --timeout=60 https://ftp.gnu.org/gnu/bison/bison-3.8.tar.xz && \
     echo "1e0a14a8bf52d878e500c33d291026b9ebe969c27b3998d4b4285ab6dbce4527  bison-3.8.tar.xz" | sha256sum -c) || \
    cp -f /fbpp_sources/bison-3.8.tar.xz .
RUN tar -xf bison-3.8.tar.xz
WORKDIR /bison-3.8

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
# Copy the binary to fuzz
CMD ["bash", "-c", "cp -r /bison-3.8/src/bison /benchmark_out_dir/    && cp /rt_grammar.json /benchmark_out_dir/ && cp /manpage.1 /benchmark_out_dir/ && cp -r /carpetfuzz_analysis /benchmark_out_dir/carpetfuzz  &&  cp /ranked_stubs.txt /benchmark_out_dir/  && cp /build.sh /benchmark_out_dir/  &&  cp /run_target.sh /benchmark_out_dir/  && cp /dict /benchmark_out_dir/ &&  cp -r /seed /benchmark_out_dir/seed "]