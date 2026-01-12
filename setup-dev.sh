#!/bin/bash
# Velo Development Setup Script - Single Source of Truth
# Run this script once after cloning the repo to set up your development environment.
#
# Usage: ./setup-dev.sh

set -euo pipefail

echo "🚀 Velo Development Setup"
echo "========================="
echo

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Check for required tools
check_tool() {
    if ! command -v "$1" &> /dev/null; then
        echo -e "${RED}❌ $1 is required but not installed.${NC}"
        echo "   Install: $2"
        exit 1
    fi
    echo -e "${GREEN}✅${NC} $1 found"
}

echo "📋 Checking required tools..."
check_tool "cargo" "https://rustup.rs"
check_tool "uv" "curl -LsSf https://astral.sh/uv/install.sh | sh"

# Install Rust toolchain (version locked in rust-toolchain.toml)
echo
echo "🔧 Installing Rust toolchain..."
rustup show active-toolchain || rustup default stable
rustup component add clippy rustfmt llvm-tools-preview 2>/dev/null || true

# Create Python venv and install deps from pyproject.toml (Single Source of Truth)
echo
echo "🐍 Setting up Python environment from pyproject.toml..."
uv venv --python 3.11
uv sync  # Single source: pyproject.toml
echo -e "${GREEN}✅${NC} Python environment ready"

# Install pre-commit hooks
echo
echo "🔗 Installing pre-commit hooks..."
git config core.hooksPath .githooks
echo -e "${GREEN}✅${NC} Pre-commit hooks installed"

echo
echo "=========================================="
echo -e "${GREEN}✨ Setup complete! You're ready to develop.${NC}"
echo
echo "Quick commands:"
echo "  cargo build --release     # Build"
echo "  cargo test                # Rust tests"
echo "  uv run pytest             # Python tests"
echo "  cargo clippy              # Lint"
echo "=========================================="
