---
description: Run the full Top 100 Baseline benchmark suite with production verification standards.
---

1. **Clear OS Cache**: Ensure cold start accuracy by dropping page cache.
   `python3 benchmarks/top100/_runner/drop_cache.py`

2. **Run Standard Benchmarks**: Execute 3 runs in Fleet Mode for maximum efficiency.
   `./benchmarks/top100/_runner/main.py --use-zygote --fleet --runs 3`

3. **Generate Report**: Compile results into REPORT.md.
   `python3 scripts/generate_report.py`
