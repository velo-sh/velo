//! Serve module - uvicorn wrapper with Zygote integration
//!
//! Provides `velo serve main:app` command for zero-config deployment.
//!
//! # Usage
//!
//! ```bash
//! velo serve main:app --workers 4 --reload
//! ```

pub mod framework;
pub mod runner;
pub mod worker;

pub use framework::{Framework, detect_framework, get_preload_modules};
pub use runner::{ServeArgs, run_server};
pub use worker::WorkerPool;
