FROM gcr.io/oss-fuzz-base/base-builder

RUN apt-get update -qq && apt-get install -qq -y --no-install-recommends \
    build-essential make autoconf libtool automake zlib1g zlib1g-dev

RUN git clone https://gitlab.com/libtiff/libtiff.git

WORKDIR $SRC/libtiff

COPY build.sh $SRC/