//! RSGI (Rust Server Gateway Interface) Host Engine
//!
//! RFC-0019: Native Sovereignty.
//! This module implements the Rust-native host that communicates with Python workers
//! via the RSGI-Velo protocol.
//!
//! Gate I/K Integration: Granian Core provides zero-copy ASGI conversion.

// RFC-0019/0025: Native Granian integration replaces this legacy UDS relay.
pub use granian_core as granian;

use thiserror::Error;

#[derive(Error, Debug)]
pub enum RSGIError {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("Protocol error: {0}")]
    Protocol(String),

    #[error("Serialization error: {0}")]
    Serialization(#[from] rmp_serde::encode::Error),

    #[error("Deserialization error: {0}")]
    Deserialization(#[from] rmp_serde::decode::Error),

    #[error("Handshake failed: {0}")]
    HandshakeFailed(String),

    #[error("Worker timeout: {0}")]
    Timeout(String),
}

pub type Result<T> = std::result::Result<T, RSGIError>;
