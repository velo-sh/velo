//! env_governance.rs - Strict Environment Whitelisting for Velo V3 (RFC-0012)
//!
//! Centralizes the constants and logic for identifying which environment variables
//! are safe to propagate from the Supervisor to the User App.

/// System variables that are generally safe to propagate and are often needed
/// by tools or for basic environment context.
pub const SAFE_SYSTEM_VARS: &[&str] = &[
    "HOME",
    "USER",
    "LOGNAME",
    "TERM",
    "LANG",
    "LC_ALL",
    "PATH",
    "PWD",
    "SHELL",
    "TZ",
    "SSH_AUTH_SOCK", // Critical for git operations in some venvs
];

/// Variables that should be set to specific values to ensure Python isolation.
/// These prevent the Zygote from being contaminated by user-site packages
/// or writing accidental byte-code to protected directories.
pub const PYTHON_ISOLATION_VARS: &[(&str, &str)] = &[
    ("PYTHONDONTWRITEBYTECODE", "1"),
    ("PYTHONUNBUFFERED", "1"),
    ("PYTHONIOENCODING", "utf-8"),
    ("PYTHONUTF8", "1"),
    ("PYTHONNOUSERSITE", "1"),
    ("PYTHONUSERBASE", "/dev/null"),
];

/// High-Performance Computing (HPC) variables to control thread affinity and count.
/// Propagated to ensure child workers respect global resource limits.
pub const HPC_VARS: &[&str] = &[
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
];

/// Forensic and Diagnostic variables used by Velo's internal infrastructure.
pub const VELO_INTERNAL_VARS: &[&str] = &["VELO_SESSION_LOG_DIR", "VELO_DEBUG", "VELO_TRACE"];

/// Checks if a variable name is a Python-specific isolation variable.
pub fn is_isolation_var(name: &str) -> bool {
    PYTHON_ISOLATION_VARS.iter().any(|(n, _)| *n == name)
}

/// Checks if a variable name is an HPC control variable.
pub fn is_hpc_var(name: &str) -> bool {
    HPC_VARS.contains(&name)
}
