//! Core Engine - Zygote, IPC, Shared Memory, and base utilities

pub mod cache;
pub mod common;
pub mod config;
pub mod custody;
pub use velo_graph as graph;
pub mod hardware;
pub mod hardware_k8s;
pub mod lifecycle;
pub mod loader;
pub mod profile;
pub mod python;
pub mod python_info;
pub mod runner;
pub mod shm;
pub mod zygote;
