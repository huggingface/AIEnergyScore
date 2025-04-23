#!/bin/bash

python /launch_backend.py
# python /check_h100.py
if [[ $? = 0 ]]; then
    optimum-benchmark --config-dir /optimum-benchmark/examples/energy_star/ $@
fi
