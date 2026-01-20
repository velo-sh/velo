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

    /// Atomically (as much as possible) cleans up and binds a new UDS listener.
    pub fn bind(&self) -> Result<UnixListener> {
        self.cleanup()?;

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
