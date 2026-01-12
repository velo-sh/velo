#![allow(unexpected_cfgs)]
//! Velo - The high-performance Python runtime for the AI era
//!
//! This library exposes internal modules for integration testing.
//! The main entry point is the `velo` binary via the `cli` module.

pub mod cache;
pub mod cli;
pub mod cmd;
pub mod common;
pub mod config;
pub mod custody; // RFC-0018: Integrated Custody
pub mod graph;
pub mod hardware;
pub mod hardware_k8s; // RFC-0011: K8s Cgroup Quota
pub mod lifecycle; // RFC-0011: Process lifecycle utilities
pub mod loader;
pub mod profile;
pub mod proxy; // RFC-0011: L7 Proxy for UDS workers
pub mod python;
pub mod python_info;
pub mod rsgi; // RFC-0019: Native Sovereignty (RSGI Host Engine)
pub mod runner;
pub mod serve;
pub mod shm; // RFC-0015: Memory Gravity
pub mod zygote;
