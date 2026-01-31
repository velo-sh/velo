#!/bin/bash
# Serverless Cold Start Runner
# Demonstrates Velo's cold start optimization for serverless workloads
#
# Usage:
#   ./examples/serverless-instant/run_hio.sh [--compare] [--runs=N]

set -e

# Configuration
DEMO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VELO_ROOT="$(cd "$DEMO_ROOT/../../" && pwd)"

COMPARE_MODE=false
RUNS=5
ran_benchmark=false

# Parse arguments
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
            echo "Serverless Computing - Cold Start Benchmark"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --compare          Run A/B comparison mode"
            echo "  --runs=N           Number of iterations (default: 5)"
            echo "  --help, -h         Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                           # Quick demo"
            echo "  $0 --compare --runs=10       # Full benchmark"
            exit 0
            ;;
    esac
done

# Standardize paths
export PYTHONPATH="$VELO_ROOT:$PYTHONPATH"
export PYTHONWARNINGS="ignore:NotOpenSSLWarning"
export HIO_SUMMARY_FILE="$VELO_ROOT/.velo_summary.txt"

# macOS fork safety
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES

# Verify uv is in PATH (needed for both modes)
command -v uv >/dev/null 2>&1 || { echo >&2 "[ERROR] uv is not installed. Please install it first."; exit 1; }

# Function to print banner
print_banner() {
    echo "=================================================="
    echo " Serverless Instant"
    echo " Cold Start → Near Zero"
    echo "=================================================="
}

# Main execution
echo ""

echo -e "\033[38;5;33m[Velo] Initializing Serverless Cold Start Demo...\033[0m"
echo -e "\033[90m  Runs: $RUNS\033[0m"

if [ "$COMPARE_MODE" = true ]; then
    # A/B Comparison Mode (using uv run for portability)
    cd "$DEMO_ROOT"
    uv run --with rich python benchmark.py --runs="$RUNS"
else
    # Quick Demo Mode
    echo -e "\n\033[1;36m=== Phase 1: CPython Cold Start ===\033[0m"
    cd "$DEMO_ROOT"
    uv run python cpython_runner.py
    
    echo -e "\n\033[1;32m=== Phase 2: Velo Zygote + Fork ===\033[0m"
    uv run python velo_runner.py
fi
