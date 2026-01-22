//! Serve module - uvicorn wrapper with Zygote integration
//!
//! Provides `velo serve main:app` command for zero-config deployment.
//!
//! # Usage
//!
//! ```bash
//! velo serve main:app --workers 4 --reload
//! ```

pub mod config;
pub mod error;
pub mod framework;
pub mod health;
pub mod runner;
pub mod watcher;
pub mod worker;

pub use config::{LogFormat, ServeArgs};
pub use error::ServeError;
pub use framework::{
    AppProtocol, Server, check_server_installed, detect_app_protocol, get_server_type,
};
pub use health::{HealthError, HealthServer};
pub use runner::{ManagedChild, run_server};
// pub use worker::WorkerPool;  // TODO: Re-implement with Zygote integration
