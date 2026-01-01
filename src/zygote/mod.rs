//! Zygote module - Process pre-warming for fast Python startup
//!
//! This module implements the Zygote pattern: pre-load heavy Python libraries
//! in a parent process, then use fork() + COW to spawn workers instantly.
//!
//! # Architecture
//!
//! ```text
//! ┌─────────────────────────────────────────────────────────────┐
//! │                      velo zygote                            │
//! ├─────────────────────────────────────────────────────────────┤
//! │  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
//! │  │   Spawner   │───▶│   Zygote    │───▶│   Workers   │     │
//! │  │   (Rust)    │    │  (Python)   │    │  (Python)   │     │
//! │  └─────────────┘    └─────────────┘    └─────────────┘     │
//! └─────────────────────────────────────────────────────────────┘
//! ```

pub mod cli;
pub mod error;
pub mod ipc;

use error::Result;
use std::path::{Path, PathBuf};

/// Check if Zygote is supported on this platform
#[cfg(unix)]
pub fn is_supported() -> bool {
    true
}

#[cfg(not(unix))]
pub fn is_supported() -> bool {
    false
}

/// Handle to a spawned worker process
pub struct WorkerHandle {
    pid: u32,
}

impl WorkerHandle {
    /// Wait for the worker to complete
    pub fn wait(&self) -> Result<i32> {
        // TODO: Implement wait
        Ok(0)
    }

    /// Get the worker's PID
    pub fn pid(&self) -> u32 {
        self.pid
    }
}

/// Zygote launcher - manages the Zygote process lifecycle
pub struct ZygoteLauncher {
    socket_path: PathBuf,
    zygote_pid: Option<u32>,
}

impl ZygoteLauncher {
    /// Create a new Zygote launcher with the specified socket path
    pub fn new(socket_path: PathBuf) -> Self {
        Self {
            socket_path,
            zygote_pid: None,
        }
    }

    /// Start the Zygote process with pre-loaded modules
    ///
    /// # Arguments
    /// * `preload` - List of Python modules to pre-import
    pub fn start(&mut self, preload: &[&str]) -> Result<()> {
        if self.is_running() {
            return Ok(());
        }

        // TODO: Implement Zygote process start
        // 1. Create Unix socket for IPC
        // 2. Spawn Python with zygote_main.py
        // 3. Wait for "READY" signal

        let _ = preload; // Suppress unused warning for now
        self.zygote_pid = Some(0); // Placeholder
        Ok(())
    }

    /// Stop the Zygote process gracefully
    pub fn stop(&mut self) -> Result<()> {
        if !self.is_running() {
            return Ok(());
        }

        // TODO: Implement graceful shutdown
        // 1. Send SHUTDOWN command over socket
        // 2. Wait for process to exit
        // 3. Cleanup socket file

        ipc::cleanup_socket(&self.socket_path);
        self.zygote_pid = None;
        Ok(())
    }

    /// Check if the Zygote process is running
    pub fn is_running(&self) -> bool {
        self.zygote_pid.is_some()
    }

    /// Get status information about the Zygote
    pub fn status(&self) -> String {
        match self.zygote_pid {
            Some(pid) => format!("Running (PID: {})", pid),
            None => "Not running".to_string(),
        }
    }

    /// Fork a new worker from the Zygote
    pub fn spawn_worker(&self, script: &Path, args: &[&str]) -> Result<WorkerHandle> {
        if !self.is_running() {
            return Err(error::ZygoteError::NotRunning);
        }

        // TODO: Implement worker spawn
        // 1. Send FORK command over socket
        // 2. Zygote forks and runs script
        // 3. Return handle to worker process

        let _ = (script, args); // Suppress unused warning for now
        Ok(WorkerHandle { pid: 0 })
    }
}

impl Drop for ZygoteLauncher {
    fn drop(&mut self) {
        // Ensure cleanup on drop
        let _ = self.stop();
    }
}
