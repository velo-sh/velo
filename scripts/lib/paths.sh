#!/bin/bash
# =============================================================================
# Velo Path SSOT (Single Source of Truth)
# =============================================================================
# This file centralizes all directory definitions to prevent path drift.
# All scripts should source this file.

# Resolve the absolute path to the project root
# We assume this file is in scripts/lib/paths.sh
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Top-level Directories
PYTHON_ROOT="$PROJECT_ROOT/python"
CRATES_ROOT="$PROJECT_ROOT/crates"
SCRIPTS_ROOT="$PROJECT_ROOT/scripts"
TESTS_ROOT="$PROJECT_ROOT/tests"

# Specific Python Package Roots
VELO_ZYGOTE_ROOT="$PYTHON_ROOT/velo_zygote"
PYTEST_VELO_ROOT="$PYTHON_ROOT/pytest_velo"

# Script Subdirectories
BENCHMARKS_SCRIPTS="$SCRIPTS_ROOT/benchmarks"
QA_SCRIPTS="$SCRIPTS_ROOT/qa"
DEV_SCRIPTS="$SCRIPTS_ROOT/dev"
MOLT_SCRIPTS="$SCRIPTS_ROOT/molt"

# Test Subdirectories
UNIT_TESTS="$TESTS_ROOT/unit"
QA_TESTS="$TESTS_ROOT/qa"
BENCHMARK_TESTS="$TESTS_ROOT/benchmarks"

# Shared Constants (for convenience)
VELO_BIN_RELEASE="$PROJECT_ROOT/target/release/velo"
VELO_BIN_DEBUG="$PROJECT_ROOT/target/debug/velo"

export PROJECT_ROOT PYTHON_ROOT CRATES_ROOT SCRIPTS_ROOT TESTS_ROOT
export VELO_ZYGOTE_ROOT PYTEST_VELO_ROOT
export BENCHMARKS_SCRIPTS QA_SCRIPTS DEV_SCRIPTS MOLT_SCRIPTS
export UNIT_TESTS QA_TESTS BENCHMARK_TESTS
export VELO_BIN_RELEASE VELO_BIN_DEBUG
