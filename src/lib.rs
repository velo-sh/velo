//! Velo - The high-performance Python runtime for the AI era
//!
//! This library exposes internal modules for integration testing.
//! The main entry point is the `velo` binary via the `cli` module.

pub mod cache;
pub mod cli;
pub mod cmd;
pub mod config;
pub mod hardware;
pub mod loader;
pub mod profile;
pub mod python;
pub mod python_info;
pub mod runner;
pub mod serve;
pub mod zygote;
