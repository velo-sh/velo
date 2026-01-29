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

# RFC-0010: Ensure shared libraries are found for uv-managed Python (Linux)
if [[ "${OSTYPE}" == "linux-gnu"* ]] && command -v uv &>/dev/null; then
    PY_EXEC=$(uv python find 2>/dev/null | head -n 1 || true)
    if [[ -n "$PY_EXEC" ]]; then
        # uv find returns the executable path. We need the lib directory.
        # Usually: .../bin/python -> .../lib/
        PY_LIB_PATH="$(dirname "$(dirname "$PY_EXEC")")/lib"
        if [[ -d "$PY_LIB_PATH" ]]; then
            export LD_LIBRARY_PATH="${PY_LIB_PATH}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
        fi
    fi
fi

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

log_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

# =============================================================================
# Phase 0: Environment Checks (FAIL FAST)
# =============================================================================
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
    
    # Check 4: Python venv
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
# Phase 3: Test Support
# =============================================================================

# Resolve Tier markers or keywords to actual pytest paths
# SSOT: This MUST stay in sync with test-suites.conf
parse_tier_to_paths() {
    local tier="${1:-full}"
    
    # Reload suites config to be sure
    source "$_CI_COMMON_DIR/test-suites.conf"
    
    case "$tier" in
        0) echo "${TIER0_TESTS[*]}" ;;
        1) echo "${TIER1_TESTS[*]}" ;;
        2) echo "${TIER2_TESTS[*]}" ;;
        3) echo "${TIER3_TESTS[*]}" ;;
        quick) echo "$TEST_PATHS_QUICK" ;;
        full) echo "$TEST_PATHS_FULL" ;;
        docker) echo "$TEST_PATHS_DOCKER" ;;
        *) echo "$tier" ;; # Assume it's a direct path
    esac
}

run_rust_tests() {
    log_step "Running Rust tests..."
    
    # SSOT: Use cargo-nextest if available (matches GitHub CI)
    # Fallback to cargo test for minimal environments
    if command -v cargo-nextest &>/dev/null || cargo nextest --version &>/dev/null 2>&1; then
        log_step "Using cargo-nextest (GitHub CI compatible)"
        cargo nextest run --lib ${EXTRA_RUST_ARGS:-}
    else
        log_step "Falling back to cargo test (nextest not installed)"
        cargo test --lib ${EXTRA_RUST_ARGS:-}
    fi
    
    log_success "Rust tests passed"
}

run_python_tests() {
    local venv_path="${1:-.venv}"
    local test_paths="${2:-tests/qa}"
    
    log_step "Running Python tests (parallel mode)..."
    
    # Activate and run
    if [[ -d "$venv_path" ]]; then
        source "$venv_path/bin/activate"
    fi
    
    # Determine parallelism
    local parallel_args=""
    if [[ "${NO_XDIST:-false}" == "false" ]] && python -c "import xdist" 2>/dev/null; then
        parallel_args="-n auto --dist loadscope"
        log_step "Using pytest-xdist: $parallel_args"
    fi
    
    # Generate JSON report for result validation
    local json_report="/tmp/pytest_results_$$.json"
    
    set +e # Allow test failure to capture artifacts
    uv run --active python -m pytest $test_paths $parallel_args -v --tb=short \
        --json-report --json-report-file="$json_report" ${EXTRA_PY_ARGS:-}
    local EXIT_CODE=$?
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
        log_error "Python tests failed with exit code $EXIT_CODE"
        exit $EXIT_CODE
    fi
    
    # ==========================================================================
    # CRITICAL: Detect false positive (all tests skipped = no real verification)
    # ==========================================================================
    if [[ -f "$json_report" ]]; then
        local passed=$(python3 -c "import json; d=json.load(open('$json_report')); print(d.get('summary',{}).get('passed',0))" 2>/dev/null || echo "0")
        local failed=$(python3 -c "import json; d=json.load(open('$json_report')); print(d.get('summary',{}).get('failed',0))" 2>/dev/null || echo "0")
        local skipped=$(python3 -c "import json; d=json.load(open('$json_report')); print(d.get('summary',{}).get('skipped',0))" 2>/dev/null || echo "0")
        local total=$(python3 -c "import json; d=json.load(open('$json_report')); print(d.get('summary',{}).get('total',0))" 2>/dev/null || echo "0")
        
        log_info "Test Summary: passed=$passed, failed=$failed, skipped=$skipped, total=$total"
        
        # FAIL if all tests were skipped (false positive protection)
        if [[ "$total" -gt 0 ]] && [[ "$passed" -eq 0 ]] && [[ "$failed" -eq 0 ]]; then
            log_fatal "FALSE POSITIVE DETECTED: All $skipped tests were SKIPPED, no actual tests ran!"
            echo ""
            log_error "This is NOT a valid CI pass. Ensure VELO_FORCE_HEAVY=1 is set for full regression."
            exit 1
        fi
        
        rm -f "$json_report"
    else
        log_warn "No JSON report found, cannot validate test execution"
    fi
    
    log_success "Python tests passed"
}

# =============================================================================
# Phase 4: Lint
# =============================================================================
run_clippy() {
    log_step "Running Clippy (all crates)..."
    cargo clippy --all-targets --all-features -- -D warnings
    log_success "Clippy passed"
}

# SSOT: Per-crate clippy (for GitHub Actions matrix jobs)
run_clippy_crate() {
    local crate="$1"
    log_step "Running Clippy on crate: $crate..."
    cargo clippy -p "$crate" --all-targets --all-features -- -D warnings
    log_success "Clippy passed for $crate"
}

run_fmt_check() {
    log_step "Checking format..."
    cargo fmt --check
    log_success "Format OK"
}

# =============================================================================
# SSOT: Per-crate Rust Tests (for GitHub Actions matrix jobs)
# =============================================================================
run_rust_tests_crate() {
    local crate="$1"
    log_step "Running Rust tests for crate: $crate..."
    
    # SSOT: Always use cargo-nextest for consistency with GitHub CI
    if command -v cargo-nextest &>/dev/null || cargo nextest --version &>/dev/null 2>&1; then
        cargo nextest run -p "$crate"
    else
        log_warn "cargo-nextest not found, falling back to cargo test"
        cargo test -p "$crate"
    fi
    
    log_success "Rust tests passed for $crate"
}

# =============================================================================
# SSOT: Coverage with cargo-llvm-cov
# =============================================================================
run_coverage() {
    log_step "Running code coverage..."
    
    # Pre-flight MUST run separately (not as a test)
    log_step "Running pre-flight diagnostic before coverage..."
    run_pre_flight
    
    # Run coverage
    if command -v cargo-llvm-cov &>/dev/null; then
        cargo llvm-cov nextest --lcov --output-path lcov.info
        log_success "Coverage generated: lcov.info"
        
        # Check threshold (70% minimum, warning only)
        if cargo llvm-cov report --fail-under-lines 70 2>/dev/null; then
            log_success "Coverage threshold (70%) met"
        else
            log_warn "Coverage below 70% threshold (warning only)"
        fi
    else
        log_fatal "cargo-llvm-cov not installed. Run: cargo install cargo-llvm-cov"
    fi
}

# =============================================================================
# SSOT: Security Audit
# =============================================================================
run_security_audit() {
    log_step "Running security audit..."
    
    # cargo-audit
    if command -v cargo-audit &>/dev/null; then
        cargo audit
        log_success "cargo-audit passed"
    else
        log_warn "cargo-audit not installed, skipping"
    fi
    
    # cargo-deny
    if command -v cargo-deny &>/dev/null; then
        cargo deny check
        log_success "cargo-deny passed"
    else
        log_warn "cargo-deny not installed, skipping"
    fi
}

# =============================================================================
# SSOT: Python Lint (Ruff)
# =============================================================================
run_ruff_check() {
    log_step "Running Ruff Python lint..."
    
    # SSOT: These are the directories to check (excluding vendor code)
    local PYTHON_DIRS="tests/ velo_zygote/ scripts/"
    
    # Lint check (exclude vendored code)
    uv run ruff check $PYTHON_DIRS --exclude "*/_vendor/*"
    log_success "Ruff lint passed"
    
    # Format check (exclude vendored and auto-generated code)
    # constants.py is auto-generated by sync-constants.py
    uv run ruff format --check $PYTHON_DIRS --exclude "*/_vendor/*" --exclude "*/constants.py"
    log_success "Ruff format passed"
}

# =============================================================================
# Full CI Pipeline
# =============================================================================
run_full_ci() {
    local tier="${1:-full}"
    local skip_build="${SKIP_BUILD:-false}"
    local venv_path=".venv"
    
    # Step 0: Detect paths from Tier
    local test_paths=$(parse_tier_to_paths "$tier")
    
    echo ""
    echo "==================== Phase 1: Setup ===================="
    check_env_fast
    setup_python_env "$venv_path"
    
    # SSOT: Force ABI Alignment
    export PYO3_PYTHON=$(uv python find)
    log_info "ABI Alignment: PYO3_PYTHON=$PYO3_PYTHON"
    
    echo ""
    echo "==================== Phase 2: Build ===================="
    if [[ "$skip_build" == "true" ]] && [[ -f "target/release/velo" ]]; then
        log_success "Reusing existing binary (SKIP_BUILD=true)"
    else
        build_rust release
    fi
    
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
    log_success "ALL CI CHECKS PASSED (Tier: $tier)!"
    echo "=========================================="
}
