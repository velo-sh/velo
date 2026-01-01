# Velo QA Documentation

This directory contains QA testing documentation for Velo.

## Test Documents

| Phase | Document | Description |
|-------|----------|-------------|
| 1.5 | [phase-1.5-test-matrix.md](./phase-1.5-test-matrix.md) | Environment Detection feature tests |

## Quick Start

```bash
# Run smoke tests
./scripts/qa-smoke.sh

# Run full benchmark suite
uv run python benchmark_projects.py --all -n 5
```

## Reporting Issues

See [Defect Reporting](./phase-1.5-test-matrix.md#7-defect-reporting) for guidelines.
