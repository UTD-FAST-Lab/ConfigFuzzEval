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

# Parent image can be overridden at build time:
    ARG parent_image=ubuntu:22.04
    FROM $parent_image
    
    # GENERAL
    ARG CC=$FUZZER_COMP
    ARG CXX=$FUZZER_COMPXX
    ARG CFLAGS=""
    
    # CC and CXX are set to clang-18 and clang++-18 when building coverage binaries.
    # If this needs to be changed, update the Dockerfile accordingly.
    
    RUN apt-get update -qq && apt-get install -qq -y --no-install-recommends \
        build-essential make autoconf libtool automake \
        libedit-dev libreadline-dev valgrind lcov git && \
        rm -rf /var/lib/apt/lists/*
    
    # Clone PCRE2 and initialize submodules (needed for SLJIT)
    RUN git clone https://github.com/PCRE2Project/pcre2.git /pcre2 && \
        cd /pcre2 && \
        git submodule update --init --recursive
    
    WORKDIR /pcre2
    
    # Copy build script and run it
    COPY build.sh .
    RUN bash build.sh
    
    # Copy supporting files to the docker image
    COPY run_target.sh /
    COPY seed /seed
    COPY dict /
    # Copy the binary to fuzz into benchmark_out_dir when container starts
CMD ["bash", "-c", "cp -r /pcre2/pcre2test /benchmark_out_dir/  && cp /dict /benchmark_out_dir/ &&  cp /run_target.sh /benchmark_out_dir/ && cp -r /seed /benchmark_out_dir/seed"]
    