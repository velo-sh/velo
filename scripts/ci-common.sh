#!/bin/bash
# =============================================================================
# Velo CI Common Library
# =============================================================================
# Shared logic for all CI environments (local macOS, Docker Ubuntu, GitHub Actions)
#
# Usage: source this file in your CI script
#   source scripts/ci-common.sh
#
# Best Practices:
# 1. FAIL FAST: Environment checks run FIRST before any builds
# 2. DRY: All environments share this common logic
# 3. EXPLICIT ERRORS: Clear messages on what's wrong and how to fix

set -euo pipefail

# Get script directory for relative sourcing
_CI_COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source test suite configuration (SSOT)
source "$_CI_COMMON_DIR/test-suites.conf"

# =============================================================================
# Colors
# =============================================================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# =============================================================================
# Logging Helpers
# =============================================================================
log_step() {
    echo -e "${BLUE}▶${NC} $1"
}

log_success() {
    echo -e "${GREEN}✅${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}⚠️${NC} $1"
}

log_error() {
    echo -e "${RED}❌${NC} $1"
}

log_fatal() {
    echo -e "${RED}💀 FATAL:${NC} $1"
    echo ""
    echo "Fix the above error and retry."
    exit 1
}

# =============================================================================
# Phase 0: Environment Checks (FAIL FAST)
# =============================================================================
# These checks run BEFORE any build to catch misconfigurations early

check_env_fast() {
    echo ""
    echo "==================== Phase 0: Environment Checks (FAIL FAST) ===================="
    echo ""
    
    local errors=0
    
    # Check 1: Rust toolchain
    log_step "Checking Rust toolchain..."
    if ! command -v cargo &>/dev/null; then
        log_error "cargo not found"
        log_error "  Fix: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
        ((errors++))
    else
        local rust_version=$(rustc --version 2>/dev/null || echo "unknown")
        log_success "Rust: $rust_version"
    fi
    
    # Check 2: uv package manager
    log_step "Checking uv..."
    if ! command -v uv &>/dev/null; then
        log_error "uv not found"
        log_error "  Fix: curl -LsSf https://astral.sh/uv/install.sh | sh"
        ((errors++))
    else
        local uv_version=$(uv --version 2>/dev/null || echo "unknown")
        log_success "uv: $uv_version"
    fi
    
    # Check 3: Project files exist
    log_step "Checking project structure..."
    local required_files=("Cargo.toml" "pyproject.toml" "rust-toolchain.toml")
    for f in "${required_files[@]}"; do
        if [[ ! -f "$f" ]]; then
            log_error "Missing required file: $f"
            log_error "  Fix: Ensure you're in the project root directory"
            ((errors++))
        fi
    done
    if [[ $errors -eq 0 ]]; then
        log_success "Project structure OK"
    fi
    
    # Check 4: Python venv (if exists, must be uv-managed)
    log_step "Checking Python environment..."
    if [[ -d ".venv" ]]; then
        if [[ -f ".venv/pyvenv.cfg" ]]; then
            if grep -q "uv" ".venv/pyvenv.cfg" 2>/dev/null; then
                log_success ".venv is uv-managed"
            else
                log_warn ".venv exists but was NOT created by uv"
                log_warn "  Recommend: rm -rf .venv && uv venv && uv sync"
            fi
        else
            log_warn ".venv exists but has no pyvenv.cfg"
        fi
    else
        log_step ".venv not found, will create during setup"
    fi
    
    # Check 5: Docker (only warn, not required for all flows)
    if [[ "${CHECK_DOCKER:-false}" == "true" ]]; then
        log_step "Checking Docker..."
        if ! command -v docker &>/dev/null; then
            log_error "docker not found (required for --docker mode)"
            ((errors++))
        elif ! docker info &>/dev/null; then
            log_error "Docker daemon not running"
            log_error "  Fix: Start Docker Desktop or run 'systemctl start docker'"
            ((errors++))
        else
            log_success "Docker OK"
        fi
    fi
    
    echo ""
    if [[ $errors -gt 0 ]]; then
        log_fatal "Environment check failed with $errors error(s)"
    fi
    log_success "All environment checks passed!"
    echo ""
}

# =============================================================================
# Phase 1: Setup
# =============================================================================
setup_python_env() {
    local venv_path="${1:-.venv}"
    
    log_step "Setting up Python environment at $venv_path..."
    
    # Create venv if needed
    if [[ ! -d "$venv_path" ]]; then
        uv venv --python 3.11 "$venv_path"
    fi
    
    # Sync dependencies
    export UV_PROJECT_ENVIRONMENT="$venv_path"
    uv sync
    
    log_success "Python environment ready"
}

# =============================================================================
# Phase 2: Build
# =============================================================================
build_rust() {
    local mode="${1:-release}"
    
    log_step "Building Rust ($mode)..."
    
    if [[ "$mode" == "release" ]]; then
        cargo build --release
    else
        cargo build
    fi
    
    log_success "Rust build complete"
}

# ============================================
# Phase Pre-Flight: Forensic Diagnostics
# ============================================
run_pre_flight() {
    log_step "Running Forensic Pre-Flight Diagnostics..."
    # Ensure binary is already built or use cargo run
    if [[ -f "target/release/velo" ]]; then
        ./target/release/velo debug pre-flight
    else
        cargo run --release -- debug pre-flight
    fi
    log_success "Pre-flight diagnostics passed"
}

# =============================================================================
# Phase 3: Test
# =============================================================================
run_rust_tests() {
    log_step "Running Rust tests..."
    cargo test --lib
    log_success "Rust tests passed"
}

run_python_tests() {
    local venv_path="${1:-.venv}"
    local test_paths="${2:-tests/qa}"
    
    log_step "Running Python tests..."
    
    # Activate and run
    source "$venv_path/bin/activate"
    
    set +e # Allow test failure to capture artifacts
    pytest $test_paths -v
    EXIT_CODE=$?
    set -e

    # Check for failure bundles
    if ls failure-*.tar.gz 1> /dev/null 2>&1; then
        echo ""
        log_warn "Failure artifacts detected!"
        mkdir -p artifacts
        mv failure-*.tar.gz artifacts/
        log_warn "Artifacts moved to artifacts/ directory"
    fi
    
    if [[ $EXIT_CODE -ne 0 ]]; then
        log_error "Python tests failed"
        exit $EXIT_CODE
    fi
    
    log_success "Python tests passed"
}

# =============================================================================
# Phase 4: Lint
# =============================================================================
run_clippy() {
    log_step "Running Clippy..."
    cargo clippy -- -D warnings
    log_success "Clippy passed"
}

run_fmt_check() {
    log_step "Checking format..."
    cargo fmt --check
    log_success "Format OK"
}

# =============================================================================
# Full CI Pipeline
# =============================================================================
run_full_ci() {
    local venv_path="${1:-.venv}"
    # Use SSOT test paths from test-suites.conf
    local test_paths="${2:-$TEST_PATHS_DOCKER}"
    
    echo ""
    echo "==================== Phase 1: Setup ===================="
    setup_python_env "$venv_path"
    
    echo ""
    echo "==================== Phase 2: Build ===================="
    build_rust release
    
    echo ""
    echo "==================== Phase Pre-Flight: Diagnostics ===================="
    run_pre_flight
    
    echo ""
    echo "==================== Phase 3: Test ===================="
    run_rust_tests
    run_python_tests "$venv_path" "$test_paths"
    
    echo ""
    echo "==================== Phase 4: Lint ===================="
    run_clippy
    run_fmt_check
    
    echo ""
    echo "=========================================="
    log_success "ALL CI CHECKS PASSED!"
    echo "=========================================="
}
