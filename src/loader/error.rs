//! Loader error types
//!
//! All error types from Handover Section 7 安全测试矩阵

use std::path::PathBuf;
use thiserror::Error;

/// Loader error types aligned with RFC-0006 Handover
#[derive(Debug, Error)]
pub enum LoaderError {
    /// Bundle exceeds 256MB limit (DoS prevention)
    #[error("Bundle too large: {size} bytes exceeds {limit} limit")]
    BundleTooLarge { size: u64, limit: u64 },

    /// File has world-writable permissions
    #[error("Insecure permissions on {path}: mode {mode:o} is world-writable")]
    InsecurePermissions { path: PathBuf, mode: u32 },

    /// Bundle in insecure location (e.g., /tmp)
    #[error("Insecure location: {path} is in a shared directory")]
    InsecureLocation { path: PathBuf },

    /// SHA-256 hash mismatch (bundle corruption or tampering)
    #[error("Bundle corrupted: SHA-256 mismatch (expected {expected}, got {actual})")]
    BundleCorrupted { expected: String, actual: String },

    /// CRC32 mismatch for individual module
    #[error("Module corrupted: {module_name} CRC32 mismatch")]
    ModuleCorrupted { module_name: String },

    /// Invalid magic bytes (not "VELO")
    #[error("Invalid magic: expected 'VELO', got '{actual}'")]
    InvalidMagic { actual: String },

    /// Unsupported bundle version
    #[error("Invalid version: expected 1, got {version}")]
    InvalidVersion { version: u32 },

    /// Python version mismatch
    #[error(
        "Python version mismatch: bundle requires {bundle_version}, runtime is {runtime_version}"
    )]
    PythonVersionMismatch {
        bundle_version: String,
        runtime_version: String,
    },

    /// Cache tag mismatch
    #[error("Cache tag mismatch: bundle is {bundle_tag}, runtime is {runtime_tag}")]
    CacheTagMismatch {
        bundle_tag: String,
        runtime_tag: String,
    },

    /// IO error
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    /// Lock acquisition failed
    #[error("Failed to acquire build lock: {0}")]
    LockFailed(String),
}

/// Result type alias for loader operations
pub type Result<T> = std::result::Result<T, LoaderError>;
