FROM fbpp/base

ARG COVERAGE=false
ENV OUT=/fuzzer_output
ENV COVERAGE=${COVERAGE}

# ENV RUNTIME is defined at docker run
ENV RUNTIME=0


# Single CMD, branch at runtime.
# MULTI_CONFIG=1 (a runtime strategy, see runtime/): the experiment mounts runtime/
# at /runtime and the trial's configurations at /rt_configs.json, and the scripts
# there run the fuzzer's run.sh / coverage.py once per configuration.
CMD ["bash", "-c", " \
    RUN_TARGET=$(cat /benchmark/run_target.sh); \
    export RUN_TARGET; \
    if [ \"$MULTI_CONFIG\" = \"1\" ] && [ ! -f /rt_configs.json ]; then \
        echo 'MULTI_CONFIG=1 but /rt_configs.json is missing' >&2; exit 1; \
    fi; \
    if [ \"$COVERAGE\" = \"false\" ]; then \
        if [ \"$MULTI_CONFIG\" = \"1\" ]; then exec bash /runtime/multi_config_run.sh; fi; \
        exec bash fuzzer/run.sh & wait; \
    else \
        if [ \"$MULTI_CONFIG\" = \"1\" ]; then exec bash /runtime/multi_config_coverage.sh; fi; \
        exec python3 fuzzer/coverage.py; \
    fi \
"]
