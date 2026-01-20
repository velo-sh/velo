//! Miracle Fork (RFC-0029)
//!
//! High-performance fork-based execution for sub-10ms feedback loops.

use anyhow::{Context, Result, bail};
use nix::unistd::{ForkResult, fork, pipe};
use std::io::{Read, Write};

pub struct MiracleFork;

impl Default for MiracleFork {
    fn default() -> Self {
        Self::new()
    }
}

impl MiracleFork {
    pub fn new() -> Self {
        Self
    }

    /// Execute a closure in a forked child process and return the result.
    ///
    /// # Safety
    ///
    /// Child process uses libc::_exit(0) to bypass all cleanups for performance.
    pub fn execute<F, T>(&self, f: F) -> Result<T>
    where
        F: FnOnce() -> T,
        T: serde::Serialize + serde::de::DeserializeOwned,
    {
        use std::fs::File;
        use std::os::unix::io::FromRawFd;

        let (r_fd, w_fd) = pipe().context("Failed to create pipe")?;

        match unsafe { fork() } {
            Ok(ForkResult::Child) => {
                // Inside child: Close reader
                unsafe { libc::close(r_fd) };

                let mut writer = unsafe { File::from_raw_fd(w_fd) };

                // Execute task
                let result = f();

                // Serialize and send result
                let serialized = serde_json::to_vec(&result).unwrap_or_default();
                let _ = writer.write_all(&serialized);
                let _ = writer.flush();
                drop(writer);

                // BYPASS ALL CLEANUPS (The "Miracle" part)
                unsafe { libc::_exit(0) };
            }
            Ok(ForkResult::Parent { child: _ }) => {
                // Inside parent: Close writer
                unsafe { libc::close(w_fd) };

                let mut reader = unsafe { File::from_raw_fd(r_fd) };

                // Read result from child
                let mut buffer = Vec::new();
                reader
                    .read_to_end(&mut buffer)
                    .context("Failed to read from child pipe")?;

                let result: T = serde_json::from_slice(&buffer)
                    .context("Failed to deserialize child result")?;

                // Master Reaper handles the cleanup (zombie reaping)

                Ok(result)
            }
            Err(e) => bail!("Fork failed: {:?}", e),
        }
    }
}
