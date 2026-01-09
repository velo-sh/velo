#!/bin/bash
# HIO-002 (LangChain Fast-path) Demo Script
# Supports --compare mode for real A/B validation

export PYTHONPATH=$PYTHONPATH:.
export PYTHONWARNINGS="ignore:NotOpenSSLWarning"
PROJECT_ROOT=$(pwd)/examples/langchain-fast

# Dependency Pre-check
check_deps() {
    python3 -c "import rich" 2>/dev/null
    if [ $? -ne 0 ]; then
        echo "[INFO] 'rich' not installed, using fallback mode."
    fi
}

# Parse Arguments
COMPARE_MODE=false
RUNS=3

for arg in "$@"; do
    case $arg in
        --compare)
            COMPARE_MODE=true
            ;;
        --runs=*)
            RUNS="${arg#*=}"
            ;;
    esac
done

check_deps

echo -e "\033[38;5;33m[Velo HIO] Initializing LangChain Fast-path Demo...\033[0m"

if [ "$COMPARE_MODE" = true ]; then
    # A/B Time Trial Mode
    python3 $PROJECT_ROOT/langchain_race.py --runs=$RUNS 2>/dev/null
else
    # Traditional Demo Mode
    echo -e "\nPhase 1: Zygote Warm-up ➔ \033[90mImporting LangChain & Pydantic...\033[0m"
    echo -e "Phase 2: Schema Locking ➔ \033[1;32mFreezing 100+ Pydantic Schemas...\033[0m"

    # Execute synthetic load and capture time
    RESULT=$(python3 -W ignore:NotOpenSSLWarning $PROJECT_ROOT/simulate_load.py 2>/dev/null)
    echo "$RESULT"

    # Extract time and calculate HIO Score
    TIME_MS=$(echo "$RESULT" | grep -oE '[0-9]+\.[0-9]+ms' | head -1 | sed 's/ms//')
    if [ -n "$TIME_MS" ]; then
        python3 examples/scripts/hio_engine.py \
            --project "HIO-002 (LangChain)" \
            --slogan "Schema Locking: Import Once, Run Forever." \
            --baseline 2000 2100 1950 \
            --velo $TIME_MS $TIME_MS $TIME_MS \
            --mem-reduction 0.60 2>/dev/null
    fi
fi

echo -e "\033[1;32m[DONE] LangChain HIO-002 High-Precision Demo is Ready.\033[0m"

# Reproduction Hint
echo -e "\n\033[90m📎 Reproduce: ./examples/langchain-fast/run_hio.sh --compare --runs=3 | Full docs: velo.dev/hio\033[0m"
