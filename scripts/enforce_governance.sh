#!/bin/bash
# Velo Governance Enforcement Wrapper
set -e

echo "🔍 Running Velo Governance Audit..."
uv run python tests/qa/enforcer.py

if [ $? -eq 0 ]; then
    echo "✅ [SUCCESS] Codebase compliant with SPEC-0005/0006 and SOP-004."
else
    echo "❌ [FAILURE] Codebase violates architectural governance. FIX REQUIRED."
    exit 1
fi
