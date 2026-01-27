//! Granian Native Worker Integration
//!
//! RFC-0019: Native Sovereignty (Phase 7.2)
//! RFC-0025: WebSocket Architecture
//!
//! This module provides the integration layer between Velo's process management
//! and Granian's PyO3-based worker architecture.
//!
//! ## Architecture
//!
//! ```text
//! ┌─────────────────────────────────────────────────────────────────┐
//! │  Velo Master (Rust Supervisor)                                  │
//! │                     fork() (Zygote COW)                         │
//! │              ┌──────────┼──────────┬──────────┐                 │
//! │              ▼          ▼          ▼          ▼                 │
//! │  ┌────────────────┐ ┌────────────────┐ ┌────────────────┐      │
//! │  │ Worker 0       │ │ Worker 1       │ │ Worker N       │      │
//! │  │ ┌────────────┐ │ │ ┌────────────┐ │ │ ┌────────────┐ │      │
//! │  │ │ Rust/Tokio │ │ │ │ Rust/Tokio │ │ │ │ Rust/Tokio │ │      │
//! │  │ └─────┬──────┘ │ │ └─────┬──────┘ │ │ └─────┬──────┘ │      │
//! │  │       │ PyO3   │ │       │ PyO3   │ │       │ PyO3   │      │
//! │  │       ▼        │ │       ▼        │ │       ▼        │      │
//! │  │ ┌────────────┐ │ │ ┌────────────┐ │ │ ┌────────────┐ │      │
//! │  │ │ Python+GIL │ │ │ │ Python+GIL │ │ │ │ Python+GIL │ │      │
//! │  │ │ ASGI App   │ │ │ │ ASGI App   │ │ │ │ ASGI App   │ │      │
//! │  │ └────────────┘ │ │ └────────────┘ │ │ └────────────┘ │      │
//! │  └────────────────┘ └────────────────┘ └────────────────┘      │
//! └─────────────────────────────────────────────────────────────────┘
//! ```
//!
//! ## Key Components
//!
//! - [`worker_entry`]: Post-fork worker initialization (PyO3 + RSGIWorker)
//! - [`config`]: Worker configuration types
//!
//! ## Critical Constraints
//!
//! 1. **PyO3 MUST initialize AFTER fork()** - GIL state corruption otherwise
//! 2. **Socket FD must be inherited** - Not FD_CLOEXEC  
//! 3. **Zygote pre-warming still applies** - COW memory sharing

pub mod config;
pub mod worker_entry;

// Re-export Granian core types for convenient access
pub use granian_core as granian;

// Re-export key types used by Velo
pub use granian_core::callbacks::CallbackScheduler;
pub use granian_core::net::{ListenerSpec, SocketHolder};
pub use granian_core::rsgi::serve::RSGIWorker;
pub use granian_core::workers::{WorkerSignal, WorkerSignalSync};

use thiserror::Error;

/// Errors that can occur during Granian worker initialization/operation.
#[derive(Error, Debug)]
pub enum GranianError {
    #[error("Python initialization failed: {0}")]
    PythonInit(String),

    #[error("Failed to load ASGI application: {0}")]
    AppLoad(String),

    #[error("Worker startup failed: {0}")]
    WorkerStartup(String),

    #[error("Socket error: {0}")]
    Socket(String),

    #[error("PyO3 error: {0}")]
    PyO3(String),

    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
}

impl From<pyo3::PyErr> for GranianError {
    fn from(err: pyo3::PyErr) -> Self {
        Self::PyO3(err.to_string())
    }
}

impl<'py> From<pyo3::CastIntoError<'py>> for GranianError {
    fn from(err: pyo3::CastIntoError<'py>) -> Self {
        Self::PyO3(err.to_string())
    }
}

pub type Result<T> = std::result::Result<T, GranianError>;
