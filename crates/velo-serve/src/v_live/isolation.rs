//! Pipe-Fence Isolation
//!
//! This module provides atomic Unix Domain Socket (UDS) binding
//! and cleanup to ensure log integrity and process isolation.

use anyhow::{Context, Result};
use std::fs;
use std::os::unix::net::UnixListener;
use std::path::{Path, PathBuf};

pub struct PipeFence {
    path: PathBuf,
}

impl PipeFence {
    pub fn new<P: AsRef<Path>>(path: P) -> Self {
        Self {
            path: path.as_ref().to_path_buf(),
        }
    }

    /// Removes the socket file if it exists.
    pub fn cleanup(&self) -> Result<()> {
        if self.path.exists() {
            fs::remove_file(&self.path)
                .with_context(|| format!("Failed to remove stale socket at {:?}", self.path))?;
        }
        Ok(())
    }

    /// Hold a non-blocking lock on the fence path.
    /// Returns true if lock was acquired, false if already locked.
    pub fn lock(&self) -> Result<bool> {
        use std::os::unix::io::AsRawFd;

        if !self.path.exists() {
            if let Some(parent) = self.path.parent() {
                fs::create_dir_all(parent)?;
            }
            fs::File::create(&self.path)?;
        }

        let file = fs::File::open(&self.path)?;
        let fd = file.as_raw_fd();

        let res = unsafe { libc::flock(fd, libc::LOCK_EX | libc::LOCK_NB) };
        if res == 0 {
            // Leak the file handle so the lock stays held until process exit
            std::mem::forget(file);
            Ok(true)
        } else {
            Ok(false)
        }
    }

    /// Atomically (as much as possible) cleans up and binds a new UDS listener.
    pub fn bind(&self) -> Result<UnixListener> {
        self.cleanup()?;
        // ... (rest remains same)

        // Ensure parent directory exists
        if let Some(parent) = self.path.parent() {
            fs::create_dir_all(parent).with_context(|| {
                format!("Failed to create directory for socket at {:?}", parent)
            })?;
        }

        let listener = UnixListener::bind(&self.path)
            .with_context(|| format!("Failed to bind UDS to {:?}", self.path))?;

        Ok(listener)
    }
}
