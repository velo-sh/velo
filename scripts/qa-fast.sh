#!/bin/bash
# Phase 3.5 QA - Tiered Test Runner
# 
# Tier 0: Smoke (< 30s) - Binary, CLI, basic sanity
# Tier 1: Fast (< 2min) - CLI tests, no server startup  
# Tier 2: Standard (< 5min) - All tests except brutal
# Tier 3: Heavy (> 5min) - Brutal/chaos tests
#
# Usage: ./scripts/qa-fast.sh [tier]

TIER="${1:-1}"

echo "============================================================"
echo "  Phase 3.5 QA - TIER $TIER"
echo "============================================================"

case "$TIER" in
  0)
    echo "  Running: Smoke tests only (< 30s)"
    echo ""
    # Smoke tests - just CLI and binary checks, no server startup
    uv run pytest \
      "tests/qa/test_phase3_5_comprehensive.py::TestL0Smoke::test_l0_001_binary_exists" \
      "tests/qa/test_phase3_5_comprehensive.py::TestL0Smoke::test_l0_002_serve_in_help" \
      "tests/qa/test_phase3_5_comprehensive.py::TestL0Smoke::test_l0_003_uvicorn_dependency_message" \
      "tests/qa/test_phase3_5_agent_d_destroyer.py::TestPromisedFeatures::test_promise_001_help_mentions_port" \
      "tests/qa/test_phase3_5_agent_d_destroyer.py::TestPromisedFeatures::test_promise_002_help_mentions_workers" \
      --tb=line -q
    ;;
  1)
    echo "  Running: Fast tests - CLI only, no server (< 2min)"
    echo ""
    # Fast tests - security and error handling, no server startup
    uv run pytest \
      tests/qa/test_phase3_5_agent_c_security.py \
      tests/qa/test_phase3_5_hardening.py \
      "tests/qa/test_phase3_5_comprehensive.py::TestL2SadPath" \
      "tests/qa/test_phase3_5_agent_d_destroyer.py::TestErrorRecovery" \
      "tests/qa/test_phase3_5_agent_d_destroyer.py::TestPromisedFeatures" \
      --tb=line -q
    ;;
  2)
    echo "  Running: Standard tests - all except brutal (< 7min)"
    echo ""
    uv run pytest tests/qa/test_phase3_5_*.py \
      --ignore=tests/qa/test_phase3_5_leader_brutal.py \
      --tb=short -q
    ;;
  3)
    echo "  Running: Heavy tests - brutal/chaos only"
    echo ""
    uv run pytest tests/qa/test_phase3_5_leader_brutal.py \
      --tb=short -v
    ;;
  *)
    echo "Usage: $0 [0|1|2|3]"
    echo ""
    echo "  0 = Smoke   (< 30s)  - Binary and help tests"
    echo "  1 = Fast    (< 2min) - Security and error handling"
    echo "  2 = Standard(< 7min) - All except brutal"
    echo "  3 = Heavy           - Brutal/chaos tests"
    exit 1
    ;;
esac

EXIT_CODE=$?

echo ""
echo "============================================================"
if [ $EXIT_CODE -eq 0 ]; then
    echo "  ✅ Tier $TIER tests passed!"
else
    echo "  ❌ Tier $TIER failed (exit code: $EXIT_CODE)"
fi
echo "============================================================"

exit $EXIT_CODE
