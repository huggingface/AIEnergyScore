#!/bin/bash

python /check_h100.py
if [[ $? = 0 ]]; then
    optimum-benchmark --config-dir /optimum-benchmark/energy_star/ $@
fi
