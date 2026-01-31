#!/bin/bash
# VELO_FIX_V3
# FastAPI Environment Reset
set -e
export PYTHONPATH=$PYTHONPATH:.
export PYTHONWARNINGS="ignore:NotOpenSSLWarning"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPARE_MODE=false
RUNS=10
for arg in "$@"; do
    case $arg in
        --compare) COMPARE_MODE=true ;;
        --runs=*) RUNS="${arg#*=}" ;;
        --help|-h) echo "Usage: $0 [OPTIONS]" ; exit 0 ;;
    esac
done
echo -e "\033[38;5;33m[Velo HIO] Initializing FastAPI Instant... (v3)\033[0m"
if [ "$COMPARE_MODE" = true ]; then
    command -v uv >/dev/null 2>&1 || { echo >&2 "[ERROR] uv not found"; exit 1; }
    uv run --with fastapi --with uvicorn --with rich python "$PROJECT_ROOT/rollback_race.py" --runs="$RUNS"
else
    echo "Run benchmark: $0 --compare"
fi
