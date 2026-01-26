//! Serve module - uvicorn wrapper with Zygote integration
//!
//! Provides `velo serve main:app` command for zero-config deployment.

pub mod cli;
pub mod config;
pub mod error;
pub mod framework;
pub mod health;
pub mod runner;
pub mod watcher;
pub mod worker;

// Engines/Submodules
pub mod granian;
pub mod proxy;
pub mod rsgi;

pub use crate::config::{LogFormat, ServeArgs};
pub use crate::error::ServeError;
pub use crate::framework::{
    AppProtocol, Server, check_server_installed, detect_app_protocol, get_server_type,
};
pub use crate::health::{HealthError, HealthServer};
pub use crate::runner::{ManagedChild, run_server};
