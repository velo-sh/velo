#!/bin/bash
# HIO-003 (FastAPI Environment Reset) Demo Script
# Demonstrates Velo's Zygote fork-based fast recovery

set -e

export PYTHONPATH=$PYTHONPATH:.
export PYTHONWARNINGS="ignore:NotOpenSSLWarning"
export VELO_WORKSPACE="/tmp/velo_hio_003"
PROJECT_ROOT=$(pwd)/examples/fastapi-instant

mkdir -p "$VELO_WORKSPACE"

# Parse Arguments
COMPARE_MODE=false
RESETS=10

for arg in "$@"; do
    case $arg in
        --compare)
            COMPARE_MODE=true
            ;;
        --resets=*)
            RESETS="${arg#*=}"
            ;;
        --help|-h)
            echo "HIO-003 (FastAPI) - Environment Reset Benchmark"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --compare       Run A/B comparison mode"
            echo "  --resets=N      Number of environment resets (default: 10)"
            exit 0
            ;;
    esac
done

echo -e "\033[38;5;33m[Velo HIO] Initializing FastAPI Instant Demo...\033[0m"

if [ "$COMPARE_MODE" = true ]; then
    # A/B Comparison Mode (using uv run with dependencies)
    uv run --with fastapi --with uvicorn python "$PROJECT_ROOT/rollback_race.py" --resets="$RESETS"
else
    echo "Run benchmark: $0 --compare"
fi

echo -e "\033[1;32m[DONE] FastAPI HIO-003 Complete.\033[0m"
