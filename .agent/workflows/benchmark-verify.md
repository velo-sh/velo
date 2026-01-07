---
description: Run the full Top 100 Baseline benchmark suite with production verification standards.
---

1. **Clear OS Cache**: Ensure cold start accuracy by dropping page cache.
   `python3 benchmarks/top100/_runner/drop_cache.py`

2. **Run Standard Benchmarks**: Execute 10 runs for all packages to ensure statistical significance.
   `./benchmarks/top100/_runner/main.py --runs 10`

3. **Generate Report**: Compile results into REPORT.md.
   `python3 scripts/generate_report.py`
