# CarpetFuzz's option-combination analysis (find_relationship.py,
# simplify_relationship.py, generate_combination.py). Not a fuzzer image: it is
# run by hand once per benchmark with generate.sh, and its output is committed
# into benchmarks/<name>/carpetfuzz/. Follows CarpetFuzz's own Dockerfile
# (Ubuntu 20.04, Python 3.8, its pinned requirements), minus the fuzzer.
FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
        build-essential cmake git wget python3-dev python3-pip python3-setuptools

RUN git clone https://github.com/waugustus/CarpetFuzz /carpetfuzz && \
    cd /carpetfuzz && \
    git checkout 23aa377ba20b5e1f9443e399e4f9dfab229e6e29 && \
    git submodule update --init pict

WORKDIR /carpetfuzz
RUN pip3 install --no-cache-dir -r requirements.txt && \
    python3 -m spacy download en_core_web_sm-3.0.0 --direct && \
    python3 -c "import nltk; [nltk.download(p) for p in ('averaged_perceptron_tagger', 'omw-1.4', 'punkt', 'wordnet')]"
RUN wget -P models/ https://allennlp.s3.amazonaws.com/models/elmo-constituency-parser-2020.02.10.tar.gz
# Loading the parser downloads its ELMo weights (357 MB) into allennlp's cache;
# do it once here instead of on every run.
RUN cd scripts && python3 -c "from utils.nlp_util import NLPUtil; NLPUtil('../models/elmo-constituency-parser-2020.02.10.tar.gz')"

RUN cmake -DCMAKE_BUILD_TYPE=Release -S pict -B pict/build && cmake --build pict/build -j

# carpetfuzz.patch: isParallelStructure raised IndexError on a one-node parse
# tree, aborting find_relationship.py (x264's man page).
COPY carpetfuzz.patch /tmp/carpetfuzz.patch
RUN git apply /tmp/carpetfuzz.patch

ENV CarpetFuzz=/carpetfuzz
