#!/bin/bash
# Development Environment Setup Script
# Auto-installs missing dependencies

set -e

echo "============================================"
echo "  Velo Development Environment Setup"
echo "============================================"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

check_and_install() {
    local name="$1"
    local check_cmd="$2"
    local install_cmd="$3"
    
    printf "▸ Checking %-20s " "$name..."
    
    if eval "$check_cmd" &>/dev/null; then
        echo -e "${GREEN}OK${NC}"
        return 0
    else
        echo -e "${YELLOW}Installing...${NC}"
        eval "$install_cmd"
        echo -e "  ${GREEN}Done${NC}"
    fi
}

echo "== Rust Toolchain =="
check_and_install "Rust" \
    "rustc --version" \
    "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y"

check_and_install "Clippy" \
    "cargo clippy --version" \
    "rustup component add clippy"

check_and_install "Rustfmt" \
    "cargo fmt --version" \
    "rustup component add rustfmt"

check_and_install "llvm-tools" \
    "rustup component list --installed | grep llvm-tools" \
    "rustup component add llvm-tools-preview"

echo ""
echo "== Cargo Extensions =="
check_and_install "cargo-llvm-cov" \
    "cargo llvm-cov --version" \
    "cargo install cargo-llvm-cov"

check_and_install "cargo-nextest" \
    "cargo nextest --version" \
    "cargo install cargo-nextest"

echo ""
echo "== Python Environment =="
echo "▸ Creating venv and installing deps from pyproject.toml..."
uv venv --python 3.11
uv sync --extra dev  # Single source of truth: pyproject.toml
echo -e "  ${GREEN}Done${NC}"

echo ""
echo "============================================"
echo -e "  ${GREEN}All dependencies installed!${NC}"
echo "============================================"
echo ""
echo "Quick commands:"
echo "  cargo build --release     # Build"
echo "  cargo test                # Run tests"
echo "  uv run pytest             # Python tests"
echo "  cargo llvm-cov --html     # Coverage report"
echo "  cargo nextest run         # Fast parallel tests"
echo ""
