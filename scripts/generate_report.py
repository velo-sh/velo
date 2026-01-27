import json
import statistics
from pathlib import Path

RESULTS_FILE = Path("benchmarks/top100/top100_v2_results.json")
REPORT_FILE = Path("benchmarks/top100/REPORT.md")


def generate():
    with open(RESULTS_FILE) as f:
        data = json.load(f)

    results = data["results"]

    # Filter out failed results for stats calculation
    passed_results = [r for r in results if r["status"] == "PASS"]
    results.sort(key=lambda x: x["package"])

    # Stats
    total = len(results)
    passed = len(passed_results)
    l4_times = [r["L4_instant"] for r in passed_results]
    median_l4 = statistics.median(l4_times) if l4_times else 0
    under_20ms = len([t for t in l4_times if t < 20])

    # Sort by speedup (only passed results)
    results_by_speedup = sorted(passed_results, key=lambda x: x["L1_cpython"] / x["L4_instant"], reverse=True)

    md = f"""# Velo Top 100 Benchmark Report

**Date**: {data["system"]["date"]}
**System**: {data["system"]["os"]} {data["system"]["machine"]} ({data["system"]["release"]})

## Summary
- **Total Packages**: {total}
- **Pass Rate**: {passed}/{total}
- **Median Startup (L4)**: {median_l4:.1f} ms
- **Packages < 20ms**: {under_20ms} ({under_20ms / passed * 100:.1f}%)

## Highlights
### Top 5 Speedups 🚀
| Package | L1 (CPython) | L4 (Velo) | Speedup |
|---|---|---|---|
"""
    for r in results_by_speedup[:5]:
        speedup = r["L1_cpython"] / r["L4_instant"]
        md += f"| **{r['package']}** | {r['L1_cpython']:.1f}ms | **{r['L4_instant']:.1f}ms** | **{speedup:.1f}x** |\\n"

    md += """
### Slowest Startups (L4)
| Package | L1 (CPython) | L4 (Velo) | Speedup |
|---|---|---|---|
"""
    # Sort by L4 time desc (only passed results)
    results_by_slowest = sorted(passed_results, key=lambda x: x["L4_instant"], reverse=True)
    for r in results_by_slowest[:5]:
        speedup = r["L1_cpython"] / r["L4_instant"]
        md += f"| **{r['package']}** | {r['L1_cpython']:.1f}ms | {r['L4_instant']:.1f}ms | {speedup:.1f}x |\\n"

    md += """
## Full Results

| Package | Category | L1 (CPython) | L2 (Velo Cold) | L3 (Bundle) | L4 (Instant) | Speedup | Status |
|---|---|---|---|---|---|---|---|
"""

    for r in results:
        status_icon = "✅" if r["status"] == "PASS" else "❌"

        if r["status"] == "PASS":
            speedup = r["L1_cpython"] / r["L4_instant"]
            # Highlight L4 if < 20ms
            l4_str = f"**{r['L4_instant']:.1f}ms**" if r["L4_instant"] < 20 else f"{r['L4_instant']:.1f}ms"
            md += f"| {r['package']} | {r['category']} | {r['L1_cpython']:.1f}ms | {r['L2_velo_zero']:.1f}ms | {r['L3_bundle']:.1f}ms | {l4_str} | {speedup:.1f}x | {status_icon} |\\n"
        else:
            # Failed benchmark - show error
            md += f"| {r['package']} | {r['category']} | - | - | - | FAILED | - | {status_icon} |\\n"

    with open(REPORT_FILE, "w") as f:
        f.write(md)

    print(f"Generated {REPORT_FILE}")


if __name__ == "__main__":
    generate()
