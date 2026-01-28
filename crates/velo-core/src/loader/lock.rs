//! Build lock for preventing thundering herd
//!
//! RFC-0006 Handover Section 6: 构建锁 (flock)
//! Crash-safe: lock auto-releases on fd close

use std::fs::{File, OpenOptions};
use std::path::Path;

use crate::loader::error::{LoaderError, Result};

#[cfg(unix)]
use fs2::FileExt;
#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;

/// Build lock using flock (crash-safe)
#[cfg(unix)]
pub struct BuildLock {
    file: File,
}

#[cfg(unix)]
impl BuildLock {
    /// Acquire exclusive lock (blocking)
    ///
    /// Handover Section 6: flock crash-safe implementation
    pub fn acquire(path: &Path) -> Result<Self> {
        // Create parent directory if needed
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }

        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false) // Keep existing file (lock semantics)
            .mode(0o600) // Owner-only
            .open(path)?;

        // Exclusive lock - other processes wait
        file.lock_exclusive()
            .map_err(|e: std::io::Error| LoaderError::LockFailed(e.to_string()))?;

        Ok(Self { file })
    }

    /// Try to acquire lock without blocking
    pub fn try_acquire(path: &Path) -> Result<Self> {
        // Create parent directory if needed
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }

        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false) // Keep existing file (lock semantics)
            .mode(0o600)
            .open(path)?;

        // Try exclusive lock - return immediately if not available
        file.try_lock_exclusive()
            .map_err(|e: std::io::Error| LoaderError::LockFailed(e.to_string()))?;

        Ok(Self { file })
    }
}

#[cfg(unix)]
impl Drop for BuildLock {
    fn drop(&mut self) {
        // Lock is automatically released when file is closed
        // fs2 handles this via flock semantics
        let _ = self.file.unlock();
    }
}

/// Non-Unix stub
#[cfg(not(unix))]
pub struct BuildLock {
    _file: File,
}

#[cfg(not(unix))]
impl BuildLock {
    pub fn acquire(path: &Path) -> Result<Self> {
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .open(path)?;
        Ok(Self { _file: file })
    }

    pub fn try_acquire(path: &Path) -> Result<Self> {
        Self::acquire(path)
    }
}
