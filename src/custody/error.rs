//! Custody error types

use std::io;
use std::path::PathBuf;
use thiserror::Error;

/// Result type for custody operations
pub type Result<T> = std::result::Result<T, CustodyError>;

/// Errors that can occur during custody operations
#[derive(Error, Debug)]
pub enum CustodyError {
    /// Failed to extract embedded binary
    #[error("failed to extract toolchain to {path}: {source}")]
    ExtractionFailed {
        path: PathBuf,
        #[source]
        source: io::Error,
    },

    /// Binary integrity check failed
    #[error("integrity check failed for {path}: expected {expected}, got {actual}")]
    IntegrityFailed {
        path: PathBuf,
        expected: String,
        actual: String,
    },

    /// Toolchain execution failed
    #[error("toolchain execution failed: {0}")]
    ExecutionFailed(String),

    /// Environment fingerprint mismatch
    #[error("environment fingerprint mismatch: {0}")]
    FingerprintMismatch(String),

    /// State file I/O error
    #[error("state file error at {path}: {source}")]
    StateFileError {
        path: PathBuf,
        #[source]
        source: io::Error,
    },

    /// Sync operation failed
    #[error("uv sync failed: {0}")]
    SyncFailed(String),

    /// Platform not supported
    #[error("platform not supported for embedded toolchain")]
    UnsupportedPlatform,

    /// Toolchain not found after extraction
    #[error("toolchain binary not found at {0}")]
    ToolchainNotFound(PathBuf),

    /// Permission error during extraction
    #[error("permission error: {0}")]
    PermissionError(String),
}
