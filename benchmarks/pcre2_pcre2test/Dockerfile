FROM gcr.io/oss-fuzz-base/base-builder

RUN apt-get update -qq && apt-get install -qq -y --no-install-recommends \
    build-essential make autoconf libtool automake

RUN git clone https://github.com/PCRE2Project/pcre2.git

WORKDIR $SRC/pcre2

COPY build.sh $SRC/
