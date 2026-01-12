#!/usr/bin/env bash
# Unified Measurement Script - Run all three modes and compare
set -e
cd "$(dirname "$0")/.."

echo "╔══════════════════════════════════════════════════════════╗"
echo "║       Velo AI Serverless Demo - Cold Start Comparison    ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

echo "== 1/3: Baseline Python =="
bash scripts/run-python.sh
echo ""

echo "== 2/3: Docker Python =="
if command -v docker &> /dev/null; then
    bash scripts/run-docker.sh
else
    echo "⚠️  Docker not available. Skipping."
fi
echo ""

echo "== 3/3: Velo Runtime =="
bash scripts/run-velo.sh
echo ""

echo "╔══════════════════════════════════════════════════════════╗"
echo "║                      Comparison Complete                  ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "What you just saw:"
echo "  • Python: Full initialization on every start"
echo "  • Docker: Container overhead + Python initialization"
echo "  • Velo:   Pre-warmed runtime, near-instant start"
echo ""
echo "This is why Python AI on serverless never made sense — until now."
