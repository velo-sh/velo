//! Zygote error types

use std::fmt;

/// Result type alias for Zygote operations
pub type Result<T> = std::result::Result<T, ZygoteError>;

/// Errors that can occur during Zygote operations
#[derive(Debug, Clone)]
pub enum ZygoteError {
    /// Failed to connect to Zygote socket
    ConnectionFailed(String),
    /// Socket I/O error
    SocketError(String),
    /// Protocol/serialization error
    ProtocolError(String),
    /// Fork operation failed
    ForkFailed(String),
    /// Zygote process is not running
    NotRunning,
    /// Failed to start Zygote process
    StartFailed(String),
    /// Zygote not supported on this platform
    NotSupported,
    /// RFC-0012: Security invariant violation (Sandbox Breach / Untrusted Path)
    SecurityViolation(String),
    /// Generic I/O error
    IOError(String),
}

impl fmt::Display for ZygoteError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ZygoteError::ConnectionFailed(msg) => write!(f, "Connection failed: {}", msg),
            ZygoteError::SocketError(msg) => write!(f, "Socket error: {}", msg),
            ZygoteError::ProtocolError(msg) => write!(f, "Protocol error: {}", msg),
            ZygoteError::ForkFailed(msg) => write!(f, "Fork failed: {}", msg),
            ZygoteError::NotRunning => write!(f, "Zygote is not running"),
            ZygoteError::StartFailed(msg) => write!(f, "Failed to start Zygote: {}", msg),
            ZygoteError::NotSupported => write!(f, "Zygote is not supported on this platform"),
            ZygoteError::SecurityViolation(msg) => write!(f, "🚨 SECURITY VIOLATION: {}", msg),
            ZygoteError::IOError(msg) => write!(f, "I/O error: {}", msg),
        }
    }
}

impl std::error::Error for ZygoteError {}
