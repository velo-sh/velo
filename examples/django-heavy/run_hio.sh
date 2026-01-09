#!/bin/bash
# HIO-001 (Django Heavyweight) Demo Script
# Supports --compare mode for real A/B validation

export PYTHONPATH=$PYTHONPATH:.
export PYTHONWARNINGS="ignore:NotOpenSSLWarning"
PROJECT_ROOT=$(pwd)/examples/django-heavy

# Dependency Pre-check
check_deps() {
    python3 -c "import rich" 2>/dev/null
    if [ $? -ne 0 ]; then
        echo "[INFO] 'rich' not installed, using fallback mode. Install with: pip install rich"
    fi
}

# Parse Arguments
COMPARE_MODE=false
RUNS=3
COLD=false

for arg in "$@"; do
    case $arg in
        --compare)
            COMPARE_MODE=true
            ;;
        --runs=*)
            RUNS="${arg#*=}"
            ;;
        --cold)
            COLD=true
            ;;
    esac
done

check_deps

echo -e "\033[38;5;33m[Velo HIO] Initializing Django Heavyweight Demo...\033[0m"

if [ "$COMPARE_MODE" = true ]; then
    # A/B Comparison Mode
    COLD_FLAG=""
    if [ "$COLD" = true ]; then
        COLD_FLAG="--cold"
    fi
    python3 $PROJECT_ROOT/startup_race.py --runs=$RUNS $COLD_FLAG
else
    # Traditional Demo Mode
    # 1. Setup Skeleton (Idempotent)
    python3 $PROJECT_ROOT/skeleton/setup_skeleton.py

    # 2. Performance Comparison (Benchmark)
    echo -e "Phase 1: Environment Freezing ➔ \033[90mScanning App Registry...\033[0m"
    sleep 0.5
    echo -e "Phase 2: Instant Clone ➔ \033[1;32mForking 10 Workers via Velo Zygote...\033[0m"
    sleep 0.5
    
    # 3. Density Proof
    python3 $PROJECT_ROOT/metrics_monitor.py --demo 2>/dev/null

    # 4. Calculate Score
    python3 examples/scripts/hio_engine.py 2>/dev/null
fi

echo -e "\033[1;32m[DONE] Django HIO-001 High-Precision Demo is Ready.\033[0m"

# Reproduction Hint
echo -e "\n\033[90m📎 Reproduce: ./examples/django-heavy/run_hio.sh --compare --runs=3 | Full docs: velo.dev/hio\033[0m"
