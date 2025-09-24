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
ARG COVERAGE=$COVERAGE_FLAGS
export CC=clang
export CXX=clang++
export CFLAGS="-g -O1 -fno-omit-frame-pointer"
export CXXFLAGS="-g -O1 -fno-omit-frame-pointer"
export CPPFLAGS="-I/LIBPNG_FUZZER/zlib"
export LDFLAGS="-L/LIBPNG_FUZZER/zlib"
export ASAN_OPTIONS="detect_leaks=0:allocator_may_return_null=1:halt_on_error=1:symbolize=1"
export UBSAN_OPTIONS="halt_on_error=1"
export LIBPNG_DIR=libpng
export ZLIB_DIR=zlib
export HARNESS_DIR=harness
# GENERAL
# CC and CXX are set to clang-18 and clang++-18 wheb building coverage bianries
# If this needs to be changed, update the Dockerfile accordingly.

RUN mkdir /LIBPNG_FUZZER

RUN apt-get update -qq && apt-get install clang llvm build-essential

RUN git clone --depth 1 https://github.com/madler/zlib.git /LIBPNG_FUZZER/zlib
WORKDIR /LIBPNG_FUZZER/zlib
RUN ./configure
RUN make -j$(nproc)

RUN git clone --depth 1 https://github.com/pnggroup/libpng.git /LIBPNG_FUZZER/libpng
WORKDIR /LIBPNG_FUZZER/libpng
COPY build.sh .
RUN bash build.sh

WORKDIR /LIBPNG_FUZZER

RUN clang++ -g -O1 -std=c++11   -fno-omit-frame-pointer   -fsanitize=fuzzer,address   -I$LIBPNG_DIR -I$ZLIB_DIR   $HARNESS_DIR/libpng_read_fuzzer.cc   $LIBPNG_DIR/.libs/libpng16.a   $ZLIB_DIR/libz.a   -o libpng_read_fuzzer
RUN ./libpng_read_fuzzer corpus -dict=$HARNESS_DIR/png.dict -rss_limit_mb=2000D -max_total_time=3600


# Copy supporting files to the docker image
COPY run_target.sh /
COPY seed /seed
COPY dict /
COPY ranked_stubs.txt /
COPY build.sh /

COPY rt_grammar.json /
# Copy the binary to fuzz
CMD ["bash", "-c", "cp -r /libpng/pngimage /benchmark_out_dir/      && cp /rt_grammar.json /benchmark_out_dir/  &&  cp /build.sh /benchmark_out_dir/  && cp /ranked_stubs.txt /benchmark_out_dir/  &&  cp /dict /benchmark_out_dir/  && cp /run_target.sh /benchmark_out_dir/ && cp -r /seed /benchmark_out_dir/seed"]













# fuzzing
sudo apt install clang llvm build-essential
export CC=clang
export CXX=clang++
export CFLAGS="-g -O1 -fno-omit-frame-pointer"
export CXXFLAGS="-g -O1 -fno-omit-frame-pointer"
git clone --depth 1 https://github.com/madler/zlib.git
cd ./zlib
./configure
make -j$(nproc)
cd ..
git clone --depth 1 https://github.com/pnggroup/libpng.git
cd ./libpng
export CPPFLAGS="-I$PWD/../zlib"
export LDFLAGS="-L$PWD/../zlib"
autoreconf -f -i
./configure --with-zlib-prefix=../zlib
make -j$(nproc) libpng16.la



#add harness containing libpng_read_fuzzer.cc and  png.dict
#add corpus containing png files

cd ..
LIBPNG_DIR=libpng
ZLIB_DIR=zlib
HARNESS_DIR=harness
ls -l $HARNESS_DIR/libpng_read_fuzzer.cc $HARNESS_DIR/png.dict || true

clang++ -g -O1 -std=c++11   -fno-omit-frame-pointer   -fsanitize=fuzzer,address   -I$LIBPNG_DIR -I$ZLIB_DIR   $HARNESS_DIR/libpng_read_fuzzer.cc   $LIBPNG_DIR/.libs/libpng16.a   $ZLIB_DIR/libz.a   -o libpng_read_fuzzer
export ASAN_OPTIONS="detect_leaks=0:allocator_may_return_null=1:halt_on_error=1:symbolize=1"
export UBSAN_OPTIONS="halt_on_error=1"
./libpng_read_fuzzer corpus -dict=$HARNESS_DIR/png.dict -rss_limit_mb=2000D -max_total_time=3600






# # for llvm cov
sudo apt install clang llvm build-essential
export CC=clang
export CXX=clang++
export CFLAGS="-fprofile-instr-generate -fcoverage-mapping"
export CXXFLAGS="-fprofile-instr-generate -fcoverage-mapping"
git clone --depth 1 https://github.com/madler/zlib.git
cd ./zlib
export CC=clang
./configure
make -j$(nproc)
cd ..
git clone --depth 1 https://github.com/pnggroup/libpng.git
cd ./libpng
export CPPFLAGS="-I$PWD/../zlib"
export LDFLAGS="-L$PWD/../zlib"
autoreconf -f -i
./configure --with-zlib-prefix=../zlib
make -j$(nproc) libpng16.la



#add harness containing libpng_read_fuzzer.cc and  png.dict
#add corpus containing png files

cd ..
LIBPNG_DIR=libpng
ZLIB_DIR=zlib
HARNESS_DIR=harness
ls -l $HARNESS_DIR/libpng_read_fuzzer.cc $HARNESS_DIR/png.dict || true

clang++ -fprofile-instr-generate -fcoverage-mapping -std=c++11  -fsanitize=fuzzer,address   -I$LIBPNG_DIR -I$ZLIB_DIR   $HARNESS_DIR/libpng_read_fuzzer.cc   $LIBPNG_DIR/.libs/libpng16.a   $ZLIB_DIR/libz.a   -o libpng_read_fuzzer
export ASAN_OPTIONS="detect_leaks=0:allocator_may_return_null=1:halt_on_error=1:symbolize=1"
export UBSAN_OPTIONS="halt_on_error=1"
export LLVM_PROFILE_FILE="profraw-%p.profraw"
./libpng_read_fuzzer corpus -dict=$HARNESS_DIR/png.dict -rss_limit_mb=2000D -max_total_time=3600
