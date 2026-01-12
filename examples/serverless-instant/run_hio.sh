#!/bin/bash
# HIO-004 (Serverless Instant) Demo Script
# Demonstrates Velo's cold start optimization for serverless workloads
#
# Usage:
#   ./examples/serverless-instant/run_hio.sh [--compare] [--scenario=single|burst|memory] [--runs=N]

set -e

# Configuration
DEMO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VELO_ROOT="$(cd "$DEMO_ROOT/../../" && pwd)"

# Default arguments
COMPARE_MODE=false
SCENARIO="single"
RUNS=5

# Parse arguments
for arg in "$@"; do
    case $arg in
        --compare)
            COMPARE_MODE=true
            ;;
        --scenario=*)
            SCENARIO="${arg#*=}"
            ;;
        --runs=*)
            RUNS="${arg#*=}"
            ;;
        --help|-h)
            echo "HIO-004 (Serverless Instant) - Cold Start Benchmark"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --compare          Run A/B comparison mode"
            echo "  --scenario=TYPE    Benchmark scenario: single, burst, memory (default: single)"
            echo "  --runs=N           Number of iterations (default: 5)"
            echo "  --help, -h         Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                           # Quick demo"
            echo "  $0 --compare                 # A/B comparison"
            echo "  $0 --compare --scenario=burst --runs=10"
            exit 0
            ;;
    esac
done

# Standardize paths
export PYTHONPATH="$VELO_ROOT:$PYTHONPATH"
export PYTHONWARNINGS="ignore:NotOpenSSLWarning"

# macOS fork safety
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES

# RFC-0018: Velo binary path (use built binary by default)
VELO_BIN="${VELO_BIN:-$VELO_ROOT/target/release/velo}"
if [ ! -x "$VELO_BIN" ]; then
    VELO_BIN="$VELO_ROOT/target/debug/velo"
fi

# Function to print banner
print_banner() {
    $VELO_BIN python -c "from examples.scripts.hio_visual import print_header; print_header('HIO-004 (Serverless Instant)', 'Cold Start → Near Zero')" 2>/dev/null || {
        echo "=============================================="
        echo " HIO-004: Serverless Instant"
        echo " Cold Start → Near Zero"
        echo "=============================================="
    }
}

# Dependency check
check_deps() {
    echo -e "\033[90m[CHECK] Verifying dependencies via Velo (RFC-0018)...\033[0m"
    $VELO_BIN python -c "import fastapi, pydantic, sqlalchemy, numpy" 2>/dev/null || {
        echo -e "\033[31m[ERROR] Missing dependencies. Install with:\033[0m"
        echo "  uv pip install -r $DEMO_ROOT/requirements.txt"
        exit 1
    }
    echo -e "\033[32m[OK] All dependencies available.\033[0m"
}

# Main execution
print_banner
echo ""
check_deps

echo -e "\n\033[38;5;33m[Velo HIO] Initializing Serverless Instant Demo...\033[0m"
echo -e "\033[90m  Scenario: $SCENARIO | Runs: $RUNS\033[0m"

if [ "$COMPARE_MODE" = true ]; then
    # A/B Comparison Mode (RFC-0018: via Velo Integrated Python)
    cd "$DEMO_ROOT"
    $VELO_BIN run benchmark.py --scenario="$SCENARIO" --runs="$RUNS"
else
    # Quick Demo Mode
    echo -e "\n\033[1;36m=== Phase 1: CPython Cold Start ===\033[0m"
    cd "$DEMO_ROOT"
    $VELO_BIN python cpython_runner.py
    
    echo -e "\n\033[1;32m=== Phase 2: Velo Zygote + Fork ===\033[0m"
    $VELO_BIN run --zygote velo_runner.py
fi

echo -e "\n\033[1;32m[DONE] HIO-004 Serverless Instant Demo Complete.\033[0m"

# Reproduction hint
echo -e "\n\033[90m📎 Reproduce: ./examples/serverless-instant/run_hio.sh --compare | Full docs: velo.dev/hio\033[0m"
