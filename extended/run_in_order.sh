#!/usr/bin/env bash
set -euo pipefail
pkg="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
root="${1:?Usage: bash run_in_order.sh NS3_ROOT OUTPUT_ROOT [RUNS=10] [FIRST_RUN=11]}"
out="${2:?Provide an output root separate from your original results}"
runs="${3:-10}"
first="${4:-11}"
py="${RR_PYTHON:-python3}"
"$py" -c 'import matplotlib, scipy, numpy; print("PASS: Python analysis dependencies")'
"$py" "$pkg/verify_package.py"
"$py" "$pkg/install.py" --ns3-root "$root"
"$py" "$pkg/run_suite.py" --ns3-root "$root" --suite smoke \
  --first-run "$first" --out "$out/00-smoke" --resume
"$py" "$pkg/check_smoke.py" "$out/00-smoke"
for suite in step rts fixed sensitivity; do
  echo "===== $suite ====="
  "$py" "$pkg/run_suite.py" --ns3-root "$root" --suite "$suite" \
    --runs "$runs" --first-run "$first" --out "$out/$suite" --resume
  "$py" "$pkg/analyze_suite.py" "$out/$suite" --out "$out/$suite-analysis"
done
echo "COMPLETE: four experiment suites and their analyses are in $out"
