//! Velo Bundle Loader - Phase 5.0 Fast Loader Infrastructure
//!
//! RFC-0006: Provides fast Python cold start through bundled bytecode loading.
//!
//! # Security Requirements (Non-negotiable)
//!
//! - TOCTOU Prevention: Read → Verify → Load atomic sequence
//! - DoS Prevention: 256MB hard limit
//! - Permission checks: Reject world-writable and insecure locations

pub mod entry;
pub mod error;
pub mod header;
pub mod lock;
pub mod security;
pub mod verify;
