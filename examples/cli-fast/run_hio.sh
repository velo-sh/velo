#!/bin/bash
# CLI Accelerator Runner
# Demonstrates Velo's TTFL (Time To First Logic) optimization

set -e

# Configuration
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXAMPLE_DIR="$PROJECT_ROOT/examples/cli-fast"

# Visual Styles
CYAN="\033[36m"
GREEN="\033[32m"
RESET="\033[0m"

usage() {
    echo "Usage: $0 [options]"
    echo ""
    echo "Options:"
    echo "  --compare     Run A/B comparison benchmark"
    echo "  --runs=N      Number of iterations (default: 5)"
    echo "  --help        Show this help"
    exit 0
}

RUNS=5
COMPARE=false

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --compare) COMPARE=true ;;
        --runs=*) RUNS="${1#*=}" ;;
        --help) usage ;;
        *) echo "Unknown parameter: $1"; usage ;;
    esac
    shift
done

cd "$PROJECT_ROOT"

if [ "$COMPARE" = true ]; then
    # Council: Verify uv is in PATH
    command -v uv >/dev/null 2>&1 || { echo >&2 "[ERROR] uv is not installed. Please install it first."; exit 1; }

    # A/B Comparison Mode (using uv run with dependencies)
    uv run --with pydantic --with rich --with click python "$EXAMPLE_DIR/bench_race.py" --runs="$RUNS"
else
    echo -e "${CYAN}Velo: CLI Accelerator${RESET}"
    echo "--------------------------"
    echo "Run benchmark:"
    echo "  $0 --compare"
    echo ""
    echo "Full benchmark (10 runs):"
    echo "  $0 --compare --runs=10"
fi
