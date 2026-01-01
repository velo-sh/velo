#!/bin/bash
# Zygote Startup Benchmark
# Compares cold start vs Zygote warm start for Python scripts

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VELO="${SCRIPT_DIR}/../target/release/velo"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "═══════════════════════════════════════════════════════════"
echo "              Velo Zygote Startup Benchmark"
echo "═══════════════════════════════════════════════════════════"
echo

# Check if velo is built
if [[ ! -f "$VELO" ]]; then
    echo "Building velo in release mode..."
    cargo build --release --manifest-path "${SCRIPT_DIR}/../Cargo.toml"
fi

# Create test script
TEST_DIR=$(mktemp -d)
TEST_SCRIPT="${TEST_DIR}/bench_test.py"
cat > "$TEST_SCRIPT" << 'EOF'
import sys
# Simple script for timing
print("ok")
EOF

# Heavy import script (simulates FastAPI-like app)
HEAVY_SCRIPT="${TEST_DIR}/bench_heavy.py"
cat > "$HEAVY_SCRIPT" << 'EOF'
import json
import os
import sys
import hashlib
import datetime
print("ok")
EOF

echo "▸ Test 1: Simple Script (cold vs warm)"
echo "─────────────────────────────────────"

# Cold start timing
echo -n "  Cold start:   "
COLD_START=$(python3 -c "
import subprocess
import time
start = time.perf_counter()
subprocess.run(['$VELO', 'run', '$TEST_SCRIPT'], capture_output=True)
print(f'{(time.perf_counter() - start) * 1000:.1f}')
")
echo "${COLD_START}ms"

# Start Zygote
echo -n "  Starting Zygote... "
$VELO zygote start 2>/dev/null || true
sleep 0.5
echo "ready"

# Warm start timing
echo -n "  Warm start:   "
WARM_START=$(python3 -c "
import subprocess
import time
start = time.perf_counter()
subprocess.run(['$VELO', 'run', '--zygote', '$TEST_SCRIPT'], capture_output=True)
print(f'{(time.perf_counter() - start) * 1000:.1f}')
")
echo "${WARM_START}ms"

# Calculate speedup
SPEEDUP=$(python3 -c "print(f'{float($COLD_START) / float($WARM_START):.1f}')")
echo -e "  ${GREEN}Speedup: ${SPEEDUP}x${NC}"
echo

echo "▸ Test 2: Heavy Imports (cold vs warm)"
echo "─────────────────────────────────────"

# Cold start timing
echo -n "  Cold start:   "
COLD_HEAVY=$(python3 -c "
import subprocess
import time
start = time.perf_counter()
subprocess.run(['$VELO', 'run', '$HEAVY_SCRIPT'], capture_output=True)
print(f'{(time.perf_counter() - start) * 1000:.1f}')
")
echo "${COLD_HEAVY}ms"

# Restart Zygote with preload
$VELO zygote stop 2>/dev/null || true
sleep 0.2
echo -n "  Starting Zygote with preload... "
$VELO zygote start --preload json,hashlib,datetime 2>/dev/null || true
sleep 0.5
echo "ready"

# Warm start timing
echo -n "  Warm start:   "
WARM_HEAVY=$(python3 -c "
import subprocess
import time
start = time.perf_counter()
subprocess.run(['$VELO', 'run', '--zygote', '$HEAVY_SCRIPT'], capture_output=True)
print(f'{(time.perf_counter() - start) * 1000:.1f}')
")
echo "${WARM_HEAVY}ms"

SPEEDUP2=$(python3 -c "print(f'{float($COLD_HEAVY) / float($WARM_HEAVY):.1f}')")
echo -e "  ${GREEN}Speedup: ${SPEEDUP2}x${NC}"
echo

# Cleanup
$VELO zygote stop 2>/dev/null || true
rm -rf "$TEST_DIR"

echo "═══════════════════════════════════════════════════════════"
echo "                    Benchmark Complete"
echo "═══════════════════════════════════════════════════════════"
