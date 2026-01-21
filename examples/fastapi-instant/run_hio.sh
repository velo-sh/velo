#!/bin/bash
# HIO-003 (FastAPI Environment Reset) Demo Script
# Demonstrates Velo's Zygote fork-based fast recovery

set -e

export PYTHONPATH=$PYTHONPATH:.
export PYTHONWARNINGS="ignore:NotOpenSSLWarning"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse Arguments
COMPARE_MODE=false
RUNS=10
ran_benchmark=false

for arg in "$@"; do
    case $arg in
        --compare)
            COMPARE_MODE=true
            ran_benchmark=true
            ;;
        --runs=*|--resets=*)
            RUNS="${arg#*=}"
            ;;
        --help|-h)
            echo "HIO-003 (FastAPI) - Environment Reset Benchmark"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --compare       Run A/B comparison mode"
            echo "  --runs=N        Number of environment resets (default: 10)"
            exit 0
            ;;
    esac
done

echo -e "\033[38;5;33m[Velo HIO] Initializing FastAPI Instant Demo...\033[0m"

if [ "$COMPARE_MODE" = true ]; then
    # Council: Verify uv is in PATH
    command -v uv >/dev/null 2>&1 || { echo >&2 "[ERROR] uv is not installed. Please install it first."; exit 1; }
    
    # A/B Comparison Mode (using uv run with dependencies)
    uv run --with fastapi --with uvicorn --with rich python "$PROJECT_ROOT/rollback_race.py" --runs="$RUNS"
else
    echo "Run benchmark: $0 --compare"
fi

if [ "$ran_benchmark" = true ]; then
    echo -e "\033[1;32m[DONE] FastAPI HIO-003 Complete.\033[0m"
fi
