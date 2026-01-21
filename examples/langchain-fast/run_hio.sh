#!/bin/bash
# HIO-002 (LangChain/Pydantic Fast-path) Demo Script
# Demonstrates Velo's schema pre-locking optimization

set -e

export PYTHONPATH=$PYTHONPATH:.
export PYTHONWARNINGS="ignore:NotOpenSSLWarning"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse Arguments
COMPARE_MODE=false
RUNS=20
ran_benchmark=false

for arg in "$@"; do
    case $arg in
        --compare)
            COMPARE_MODE=true
            ran_benchmark=true
            ;;
        --runs=*)
            RUNS="${arg#*=}"
            ;;
        --help|-h)
            echo "HIO-002 (LangChain/Pydantic) - Schema Generation Benchmark"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --compare     Run A/B comparison mode"
            echo "  --runs=N      Number of iterations (default: 20)"
            exit 0
            ;;
    esac
done

echo -e "\033[38;5;33m[Velo HIO] Initializing LangChain Fast-path Demo...\033[0m"

if [ "$COMPARE_MODE" = true ]; then
    # Council: Verify uv is in PATH
    command -v uv >/dev/null 2>&1 || { echo >&2 "[ERROR] uv is not installed. Please install it first."; exit 1; }

    # A/B Comparison Mode (using uv run with dependencies)
    uv run --with pydantic python "$PROJECT_ROOT/langchain_race.py" --runs="$RUNS"
else
    echo "Run benchmark: $0 --compare"
fi

if [ "$ran_benchmark" = true ]; then
    echo -e "\033[1;32m[DONE] LangChain HIO-002 Complete.\033[0m"
fi
