FROM fbpp/base

RUN git clone https://github.com/rc0r/afl-utils.git
RUN apt-get update && apt-get install -y gdb

WORKDIR /afl-utils
RUN python3 setup.py install
COPY run.sh .


CMD ["bash", "run.sh"]