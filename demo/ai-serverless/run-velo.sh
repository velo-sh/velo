#!/usr/bin/env bash
# Velo: Optimized Execution
echo "⚡ Starting Velo runtime (Optimized)..."

# Ensure the binary is available. We look in release first, then debug.
VELO_BIN="../../target/release/velo"
if [ ! -f "$VELO_BIN" ]; then
    VELO_BIN="../../target/debug/velo"
fi

if [ ! -f "$VELO_BIN" ]; then
    echo "❌ Velo binary not found. Please run 'cargo build --release' first."
    exit 1
fi

START=$(date +%s%3N)

# Run via Velo. We use --zygote to show the pre-warm benefit.
$VELO_BIN run --zygote app.py &
PID=$!

# Wait until the port is open
COUNT=0
while ! nc -z localhost 8000; do   
  sleep 0.05
  COUNT=$((COUNT+1))
  if [ $COUNT -gt 200 ]; then
    echo "❌ Timeout waiting for Velo server"
    kill $PID
    exit 1
  fi
done

END=$(date +%s%3N)
RSS=$(ps -o rss= -p $PID)
echo "⏱ Total Startup Time (Velo): $((END-START))ms"
echo "💎 Memory Usage (RSS): $((RSS/1024))MB"
echo "🚀 Server ready at http://localhost:8000"
echo "Press Ctrl+C to stop."
wait $PID
