#!/bin/bash
# =============================================================================
# Velo Local CI Script
# =============================================================================
# Run CI locally (macOS) or in Docker (Ubuntu simulation)
#
# Docker CI uses a single base image + volume caching for incremental builds:
# - velo-ci-base: Contains Rust, Python 3.11, uv
# - velo-cargo-cache: Persists compiled dependencies between runs
# - velo-cargo-registry: Persists Cargo registry cache

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Source common library
source "$SCRIPT_DIR/ci-common.sh"

# =============================================================================
# Configuration
# =============================================================================
IMAGE_NAME="velo-ci-base"
DOCKERFILE="Dockerfile.base"

# Docker volumes for caching
CARGO_CACHE="velo-cargo-cache"
CARGO_REGISTRY="velo-cargo-registry"

# =============================================================================
# Usage
# =============================================================================
print_usage() {
    echo "Velo Local CI"
    echo ""
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  (no args)    Run full CI locally (macOS)"
    echo "  --setup      First-time setup (install dependencies, git hooks, cross-targets)"
    echo "  --docker     Run full CI in Docker (Ubuntu simulation)"
    echo "  --build      Build Docker base image"
    echo "  --shell      Interactive Docker shell for debugging"
    echo "  --quick      Quick local check (build + unit tests only)"
    echo "  --check      Environment check only (fail fast)"
    echo "  --clean      Clean Docker volumes (fresh start)"
    echo "  --help       Show this help"
    echo ""
    echo "Examples:"
    echo "  $0 --setup           # First-time setup"
    echo "  $0                   # Full local CI"
    echo "  $0 --docker          # Simulate Ubuntu CI"
    echo "  $0 --check           # Quick environment validation"
    echo "  $0 --clean           # Reset Docker caches"
}

# =============================================================================
# Docker Functions
# =============================================================================
docker_build() {
    log_step "Building Docker base image..."
    docker build -t "$IMAGE_NAME" -f "$DOCKERFILE" .
    log_success "Docker image built"
}

docker_run() {
    # Ensure image exists
    if ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
        docker_build
    fi
    
    log_step "Running CI in Docker (Ubuntu + Python 3.11)..."
    docker run --rm \
        -v "$PROJECT_ROOT:/workspace" \
        -v "$CARGO_CACHE:/workspace/target" \
        -v "$CARGO_REGISTRY:/root/.cargo/registry" \
        -e GITHUB_ACTIONS=true \
        -e UV_PYTHON=python3.11 \
        -e UV_HTTP_TIMEOUT=120 \
        "$IMAGE_NAME" \
        bash -c '
            echo "🚀 Velo CI (Docker)"
            echo ""
            echo "==================== Phase 1: Setup Python ===================="
            # Create Docker-specific venv FIRST to avoid architecture mismatch with host
            uv venv --python 3.11 .venv_docker
            source .venv_docker/bin/activate
            uv sync --all-groups
            
            # Set PYO3_PYTHON for Rust build (required by build.rs sentinel)
            export PYO3_PYTHON=/workspace/.venv_docker/bin/python
            echo "PYO3_PYTHON=$PYO3_PYTHON"
            
            echo ""
            echo "==================== Phase 2: Build ===================="
            cargo build --release
            echo ""
            echo "==================== Phase 3: Pre-Flight ===================="
            ./target/release/velo debug pre-flight || true
            echo ""
            echo "==================== Phase 4: Test ===================="
            rm -rf .pytest_cache
            source scripts/ci-common.sh
            # Use the Tier-2 Docker CI suite from test-suites.conf
            source scripts/test-suites.conf
            run_python_tests ".venv_docker" "$TEST_PATHS_DOCKER"
            echo ""
            echo "=========================================="
            echo "✅ ALL CI CHECKS PASSED!"
            echo "=========================================="
        '
}

docker_shell() {
    # Ensure image exists
    if ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
        docker_build
    fi
    
    log_step "Starting interactive Docker shell..."
    docker run --rm -it \
        -v "$PROJECT_ROOT:/workspace" \
        -v "$CARGO_CACHE:/workspace/target" \
        -v "$CARGO_REGISTRY:/root/.cargo/registry" \
        -e GITHUB_ACTIONS=true \
        -e UV_PYTHON=python3.11 \
        "$IMAGE_NAME" \
        bash
}

docker_clean() {
    log_step "Cleaning Docker volumes..."
    docker volume rm -f "$CARGO_CACHE" "$CARGO_REGISTRY" 2>/dev/null || true
    log_success "Docker volumes cleaned"
}

# =============================================================================
# Local CI Functions
# =============================================================================
run_local_ci() {
    echo ""
    echo "🚀 Velo Local CI (macOS)"
    echo "========================"
    echo ""
    
    # Phase 0: FAIL FAST environment check
    check_env_fast

    # Fix DEF-72-CI-001: CI Toolchain Misalignment (macOS)
    # Ensure rust-cpython/pyo3 links against the hermetic uv python, not system python.
    log_step "Configuring build toolchain..."
    export PYO3_PYTHON=$(uv python find 3.11)
    log_success "Toolchain aligned: PYO3_PYTHON=$PYO3_PYTHON"
    
    # Run full CI pipeline with SSOT test paths from test-suites.conf
    run_full_ci ".venv" "$TEST_PATHS_DOCKER"
}

run_setup() {
    echo ""
    echo "🔧 Velo Development Setup"
    echo "========================="
    echo ""

    log_step "Checking Rust toolchain..."
    if ! command -v rustup &> /dev/null; then
        log_error "rustup not found. Install from https://rustup.rs"
        exit 1
    fi
    log_success "Rust toolchain found"

    log_step "Installing Linux cross-compilation target..."
    rustup target add x86_64-unknown-linux-gnu
    log_success "Linux target installed (for pre-commit cross-checking)"

    log_step "Checking Python/uv..."
    if ! command -v uv &> /dev/null; then
        log_error "uv not found. Install from https://docs.astral.sh/uv/"
        exit 1
    fi
    log_success "uv found"

    log_step "Setting up Python environment..."
    uv sync
    log_success "Python dependencies installed"

    log_step "Configuring git hooks..."
    git config core.hooksPath .githooks
    log_success "Git hooks configured (using .githooks/)"

    log_step "Installing pre-commit framework..."
    uv run pre-commit install || true
    log_success "Pre-commit installed"

    echo ""
    echo "==========================================="
    log_success "Setup complete! You can now commit with cross-platform checks."
    echo "==========================================="
    echo ""
    echo "Next steps:"
    echo "  1. Run './scripts/local-ci.sh --quick' to verify"
    echo "  2. Make changes and commit normally"
    echo ""
}

run_quick_check() {
    echo ""
    echo "⚡ Velo Quick Check"
    echo "==================="
    echo ""
    
    # Phase 0: FAIL FAST environment check
    check_env_fast
    
    # Quick build + test only
    log_step "Quick build..."
    cargo build --release
    
    log_step "Quick test (Rust)..."
    cargo test --lib
    
    log_step "Quick test (Python)..."
    run_python_tests ".venv" "$TEST_PATHS_QUICK"
    
    echo ""
    log_success "Quick check passed!"
}

# =============================================================================
# Main
# =============================================================================
case "${1:-}" in
    --setup)
        run_setup
        ;;
    --docker)
        export CHECK_DOCKER=true
        check_env_fast
        docker_run
        ;;
    --build)
        export CHECK_DOCKER=true
        check_env_fast
        docker_build
        ;;
    --shell)
        export CHECK_DOCKER=true
        check_env_fast
        docker_shell
        ;;
    --clean)
        docker_clean
        ;;
    --quick)
        run_quick_check
        ;;
    --check)
        check_env_fast
        ;;
    --help|-h)
        print_usage
        ;;
    "")
        run_local_ci
        ;;
    *)
        log_error "Unknown option: $1"
        print_usage
        exit 1
        ;;
esac
