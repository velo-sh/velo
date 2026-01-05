//! Lifecycle management utilities
//!
//! RFC-0011: Provides utilities for safe process and socket lifecycle management.

pub mod safety;

pub use safety::{
    ensure_socket_directory, generate_worker_socket_path, set_cloexec, set_cloexec_on_all_fds,
    unlink_socket_if_exists, unlink_socket_if_exists_sync,
};
