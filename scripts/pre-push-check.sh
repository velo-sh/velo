#!/bin/bash
# pre-push-check.sh - Run all checks before pushing to avoid CI failures

set -e

echo "============================================"
echo "  Pre-Push Validation"
echo "============================================"

# 1. Cargo fmt check
echo ""
echo "→ Checking Rust formatting..."
if ! cargo fmt --all -- --check; then
    echo "❌ Format check failed. Running cargo fmt to fix..."
    cargo fmt --all
    echo "✅ Format fixed. Please review and commit the changes."
    exit 1
fi
echo "✅ Rust formatting OK"

# 2. Clippy check
echo ""
echo "→ Running clippy..."
if ! cargo clippy --all-targets --all-features -- -D warnings; then
    echo "❌ Clippy check failed. Please fix the warnings above."
    exit 1
fi
echo "✅ Clippy OK"

# 3. Python formatting (if needed)
echo ""
echo "→ Checking Python files..."
echo "✅ Python checks skipped (add ruff/black if needed)"

echo ""
echo "============================================"
echo "  ✅ All checks passed! Safe to push."
echo "============================================"
