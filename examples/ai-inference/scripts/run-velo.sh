#!/usr/bin/env bash
# Velo Runtime Execution with Cold-Start and RSS Measurement
set -e

# This script should be run from the REPOSITORY ROOT
if [ ! -f "crates/velo-cli/src/main.rs" ]; then
    echo "❌ Error: This script must be run from the repository root."
    exit 1
fi

echo "⚡ Velo Runtime (AI Inference Example)"
echo "----------------------------"

# Kill any existing process on port 8000
lsof -ti:8000 | xargs kill -9 2>/dev/null || true

# Locate Velo binary
VELO_BIN="target/release/velo"
if [ ! -f "$VELO_BIN" ]; then
    VELO_BIN="target/debug/velo"
fi

if [ ! -f "$VELO_BIN" ]; then
    echo "❌ Velo binary not found. Run 'cargo build' first."
    exit 1
fi

echo "🔍 Analyzing native dependencies (RFC-0035)..."
(cd examples/ai-inference && ../../$VELO_BIN preload analyze)
echo ""

START=$(python3 -c "import time; print(int(time.time() * 1000))")

# Run Velo from root so it finds velo_zygote
# Velo will discover examples/ai-inference/.venv automatically
$VELO_BIN run examples/ai-inference/app.py &
PID=$!

# Wait for server to be ready (max 5s)
for _ in {1..50}; do
    if nc -z localhost 8000 2>/dev/null; then
        break
    fi
    sleep 0.1
done

END=$(python3 -c "import time; print(int(time.time() * 1000))")
COLD_START=$((END - START))

# Get RSS in KB
RSS_KB=$(ps -o rss= -p $PID 2>/dev/null || echo "0")
RSS_MB=$((RSS_KB / 1024))

echo "⏱  Cold-start time: ${COLD_START} ms"
echo "📊 RSS memory:      ${RSS_MB} MB"

# Cleanup
kill $PID 2>/dev/null || true
echo "----------------------------"
