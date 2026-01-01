#!/bin/bash
#
# Velo Development Setup Script
# Run this script once after cloning the repo to set up your development environment.
#

set -e

echo "🚀 Velo Development Setup"
echo "========================="
echo

# Check for required tools
check_tool() {
    if ! command -v "$1" &> /dev/null; then
        echo "❌ $1 is required but not installed."
        echo "   Install: $2"
        exit 1
    fi
    echo "✅ $1 found"
}

echo "📋 Checking required tools..."
check_tool "cargo" "https://rustup.rs"
check_tool "uv" "curl -LsSf https://astral.sh/uv/install.sh | sh"

# Install Rust toolchain (version locked in rust-toolchain.toml)
echo
echo "🔧 Installing Rust toolchain (version locked in rust-toolchain.toml)..."
rustup show active-toolchain || rustup default stable

# Install pre-commit hooks
echo
echo "🔗 Installing pre-commit hooks..."
git config core.hooksPath .githooks
echo "✅ Pre-commit hooks installed"

# Create Python venv
echo
echo "🐍 Creating Python virtual environment..."
uv venv --python 3.11
uv pip install pytest
echo "✅ Python venv created"

# Verify setup
echo
echo "🧪 Verifying setup..."
cargo build --release
echo "✅ Build successful"

echo
echo "=========================================="
echo "✨ Setup complete! You're ready to develop."
echo
echo "Next steps:"
echo "  cargo build --release     # Build"
echo "  uv run run_tests.py       # Run tests"
echo "  cargo clippy              # Lint"
echo "=========================================="
