#!/bin/sh
# Toy analysis the agent can run via the `run` workspace tool.
echo "rows: $(tail -n +2 data.csv | wc -l | tr -d ' ')"
awk -F, 'NR>1 {sum+=$2} END {printf "total: %s\n", sum}' data.csv
