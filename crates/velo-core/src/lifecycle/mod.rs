//! Lifecycle management utilities
//!
//! RFC-0011: Provides utilities for safe process and socket lifecycle management.

pub mod v_shield;

pub use v_shield::{
    Airlock, EnvironmentShield, apply_standard_hygiene, ensure_socket_directory,
    generate_abstract_socket_name, set_cloexec, set_cloexec_on_all_fds, supports_abstract_sockets,
    unlink_socket_if_exists, unlink_socket_if_exists_sync,
};
