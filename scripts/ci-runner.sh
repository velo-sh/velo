#!/bin/bash
# =============================================================================
# Velo CI Runner (SSOT Entry Point)
# =============================================================================
# This script is the SINGLE ENTRY POINT for all CI operations.
# GitHub Actions, local CI, and Docker CI all call this script.
#
# Usage:
#   ./scripts/ci-runner.sh <command> [args...]
#
# Commands:
#   clippy-crate <crate>    Run clippy on a specific crate
#   test-crate <crate>      Run tests on a specific crate (nextest)
#   coverage                Run coverage with cargo-llvm-cov
#   audit                   Run security audit (cargo-audit + cargo-deny)
#   pre-flight              Run pre-flight diagnostics
#   fmt-check               Check code formatting
#
# SSOT Principle: All CI logic lives in ci-common.sh
# This script is just a dispatcher that calls those functions.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/ci-common.sh"

# Command dispatcher
case "${1:-help}" in
    clippy-crate)
        if [[ -z "${2:-}" ]]; then
            log_fatal "Usage: $0 clippy-crate <crate-name>"
        fi
        run_clippy_crate "$2"
        ;;
    
    test-crate)
        if [[ -z "${2:-}" ]]; then
            log_fatal "Usage: $0 test-crate <crate-name>"
        fi
        run_rust_tests_crate "$2"
        ;;
    
    coverage)
        run_coverage
        ;;
    
    audit)
        run_security_audit
        ;;
    
    pre-flight)
        run_pre_flight
        ;;
    
    fmt-check)
        run_fmt_check
        ;;
    
    help|--help|-h)
        echo "Velo CI Runner (SSOT Entry Point)"
        echo ""
        echo "Usage: $0 <command> [args...]"
        echo ""
        echo "Commands:"
        echo "  clippy-crate <crate>  Run clippy on a specific crate"
        echo "  test-crate <crate>    Run tests on a specific crate (nextest)"
        echo "  coverage              Run coverage with cargo-llvm-cov"
        echo "  audit                 Run security audit"
        echo "  pre-flight            Run pre-flight diagnostics"
        echo "  fmt-check             Check code formatting"
        ;;
    
    *)
        log_error "Unknown command: $1"
        echo "Run '$0 --help' for usage."
        exit 1
        ;;
esac
