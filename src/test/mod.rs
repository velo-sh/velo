//! Test execution module - Zygote-accelerated test coordination
//!
//! RFC-0028: pytest-velo Plugin (Phase 13)
//!
//! This module provides the Rust-side coordination for running tests
//! via Zygote COW forks for maximum performance.

pub mod coordinator;

pub use coordinator::TestCoordinator;
