FROM fbpp/base

ARG RUNTIME
ARG COVERAGE=false
ENV RUNTIME=${RUNTIME}
ENV OUT=/fuzzer_output
ENV COVERAGE=${COVERAGE}

# Single CMD, branch at runtime
CMD ["bash", "-c", " \
    if [ \"$COVERAGE\" = \"false\" ]; then \
        RUN_TARGET=$(cat /benchmark/run_target.sh); \
        export RUN_TARGET; \
        exec bash fuzzer/run.sh; \
    else \
        RUN_TARGET=$(cat /benchmark/run_target.sh); \
        export RUN_TARGET; \
        exec python3 fuzzer/coverage.py; \
    fi \
"]
