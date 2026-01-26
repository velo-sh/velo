//! Loader error types
//!
//! RFC-0006 Section 8: Error Codes (1xx-5xx categories)

use std::path::PathBuf;
use thiserror::Error;

/// Loader error types aligned with RFC-0006
///
/// Error code categories:
/// - 1xx: File I/O
/// - 2xx: Validation
/// - 3xx: Integrity
/// - 4xx: Security
/// - 5xx: Runtime
#[derive(Debug, Error)]
pub enum LoaderError {
    // === File I/O (1xx) ===
    /// File not found
    #[error("File not found: {path}")]
    FileNotFound { path: PathBuf },

    /// Read operation failed
    #[error("Read failed: {0}")]
    ReadFailed(String),

    /// Write operation failed
    #[error("Write failed: {0}")]
    WriteFailed(String),

    /// Lock acquisition failed
    #[error("Failed to acquire build lock: {0}")]
    LockFailed(String),

    // === Validation (2xx) ===
    /// Invalid magic bytes (not "VELO")
    #[error("Invalid magic: expected 'VELO', got '{actual}'")]
    InvalidMagic { actual: String },

    /// Unsupported bundle version
    #[error("Unsupported version: expected 1, got {version}")]
    InvalidVersion { version: u32 },

    /// Unsupported hash algorithm
    #[error("Unsupported hash algorithm: {algorithm}")]
    UnsupportedHashAlgorithm { algorithm: u8 },

    /// Bundle exceeds 256MB limit (DoS prevention)
    #[error("Bundle too large: {size} bytes exceeds {limit} limit")]
    BundleTooLarge { size: u64, limit: u64 },

    /// Bundle too small to contain header
    #[error("Bundle too small: {size} bytes")]
    BundleTooSmall { size: u64 },

    /// Invalid offset in bundle
    #[error("Invalid offset: {offset} exceeds bundle size {size}")]
    InvalidOffset { offset: u64, size: u64 },

    // === Integrity (3xx) ===
    /// BLAKE3 hash mismatch (bundle corruption or tampering)
    #[error("Bundle corrupted: hash mismatch (expected {expected}, got {actual})")]
    BundleCorrupted { expected: String, actual: String },

    /// Import graph hash mismatch
    #[error("Import graph tampered: hash mismatch")]
    ImportGraphTampered,

    /// Module hash mismatch
    #[error("Module corrupted: {module_name} hash mismatch")]
    ModuleCorrupted { module_name: String },

    // === Security (4xx) ===
    /// File has world-writable permissions
    #[error("Insecure permissions on {path}: mode {mode:o} is world-writable")]
    InsecurePermissions { path: PathBuf, mode: u32 },

    /// Bundle in insecure location (e.g., /tmp)
    #[error("Insecure location: {path} is in a shared directory")]
    InsecureLocation { path: PathBuf },

    /// Symlink bypass attempt
    #[error("Symlink bypass detected: {path}")]
    SymlinkBypass { path: PathBuf },

    /// Insecure bundle content (e.g. recursion limit)
    #[error("Insecure bundle: {0}")]
    InsecureBundle(String),

    // === Runtime (5xx) ===
    /// Module not found in bundle
    #[error("Module not found: {name}")]
    ModuleNotFound { name: String },

    /// Marshal operation failed
    #[error("Marshal failed: {0}")]
    MarshalFailed(String),

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
}

impl LoaderError {
    /// Get numeric error code (RFC-0006 Section 8)
    pub fn code(&self) -> u16 {
        match self {
            // File I/O (1xx)
            LoaderError::FileNotFound { .. } => 100,
            LoaderError::ReadFailed(_) => 101,
            LoaderError::WriteFailed(_) => 102,
            LoaderError::LockFailed(_) => 103,

            // Validation (2xx)
            LoaderError::InvalidMagic { .. } => 200,
            LoaderError::InvalidVersion { .. } => 201,
            LoaderError::UnsupportedHashAlgorithm { .. } => 202,
            LoaderError::BundleTooLarge { .. } => 203,
            LoaderError::BundleTooSmall { .. } => 204,
            LoaderError::InvalidOffset { .. } => 206,

            // Integrity (3xx)
            LoaderError::BundleCorrupted { .. } => 300,
            LoaderError::ImportGraphTampered => 301,
            LoaderError::ModuleCorrupted { .. } => 302,

            // Security (4xx)
            LoaderError::InsecurePermissions { .. } => 401,
            LoaderError::InsecureLocation { .. } => 400,
            LoaderError::SymlinkBypass { .. } => 402,
            LoaderError::InsecureBundle(_) => 403,

            // Runtime (5xx)
            LoaderError::ModuleNotFound { .. } => 500,
            LoaderError::MarshalFailed(_) => 501,
            LoaderError::PythonVersionMismatch { .. } => 510,
            LoaderError::CacheTagMismatch { .. } => 511,
            LoaderError::Io(_) => 101,
        }
    }
}

/// Result type alias for loader operations
pub type Result<T> = std::result::Result<T, LoaderError>;
