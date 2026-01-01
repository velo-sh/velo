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

pub mod auto_config;
pub mod cli;
pub mod error;
pub mod ipc;

use error::{Result, ZygoteError};
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::time::Duration;

/// Check if Zygote is supported on this platform
#[cfg(unix)]
pub fn is_supported() -> bool {
    true
}

#[cfg(not(unix))]
pub fn is_supported() -> bool {
    false
}

/// Find the velo_zygote Python module path
fn find_zygote_module() -> Result<PathBuf> {
    // Try relative to executable first
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(exe_dir) = exe_path.parent() {
            // Development: ../velo_zygote/main.py
            let dev_path = exe_dir.join("../velo_zygote/main.py");
            if dev_path.exists() {
                return Ok(dev_path.canonicalize().unwrap_or(dev_path));
            }

            // Installed: velo_zygote/main.py in same dir
            let installed_path = exe_dir.join("velo_zygote/main.py");
            if installed_path.exists() {
                return Ok(installed_path);
            }
        }
    }

    // Try current working directory
    let cwd_path = PathBuf::from("velo_zygote/main.py");
    if cwd_path.exists() {
        return Ok(cwd_path.canonicalize().unwrap_or(cwd_path));
    }

    Err(ZygoteError::StartFailed(
        "Could not find velo_zygote/main.py".to_string(),
    ))
}

/// Handle to a spawned worker process
pub struct WorkerHandle {
    pid: u32,
}

impl WorkerHandle {
    /// Wait for the worker to complete
    #[cfg(unix)]
    pub fn wait(&self) -> Result<i32> {
        let pid = self.pid as i32;
        loop {
            let mut status: i32 = 0;
            let result = unsafe { libc::waitpid(pid, &mut status, 0) };
            if result == -1 {
                let err = std::io::Error::last_os_error();
                if err.kind() == std::io::ErrorKind::Interrupted {
                    continue;
                }
                return Err(ZygoteError::ForkFailed(err.to_string()));
            }
            // Check if exited
            if libc::WIFEXITED(status) {
                return Ok(libc::WEXITSTATUS(status));
            }
            if libc::WIFSIGNALED(status) {
                return Ok(128 + libc::WTERMSIG(status));
            }
        }
    }

    #[cfg(not(unix))]
    pub fn wait(&self) -> Result<i32> {
        // Windows: not supported
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
    zygote_process: Option<Child>,
    python_path: Option<PathBuf>,
}

impl ZygoteLauncher {
    /// Create a new Zygote launcher with the specified socket path
    pub fn new(socket_path: PathBuf) -> Self {
        Self {
            socket_path,
            zygote_pid: None,
            zygote_process: None,
            python_path: None,
        }
    }

    /// Set the Python interpreter path
    pub fn with_python(mut self, python: PathBuf) -> Self {
        self.python_path = Some(python);
        self
    }

    /// Start the Zygote process with pre-loaded modules
    ///
    /// # Arguments
    /// * `preload` - List of Python modules to pre-import
    #[cfg(unix)]
    pub fn start(&mut self, preload: &[&str]) -> Result<()> {
        if self.is_running() {
            return Ok(());
        }

        // Find Python interpreter
        let python = self.python_path.clone().unwrap_or_else(|| {
            // Default to python3
            PathBuf::from("python3")
        });

        // Find zygote module
        let zygote_module = find_zygote_module()?;

        // Build command
        let mut cmd = Command::new(&python);
        cmd.arg(&zygote_module)
            .arg("--socket")
            .arg(&self.socket_path);

        if !preload.is_empty() {
            cmd.arg("--preload");
            for module in preload {
                cmd.arg(module);
            }
        }

        // Spawn the Zygote process
        let child = cmd
            .spawn()
            .map_err(|e| ZygoteError::StartFailed(format!("Failed to spawn Zygote: {}", e)))?;

        let pid = child.id();
        self.zygote_process = Some(child);
        self.zygote_pid = Some(pid);

        // Wait for socket to be created (with timeout)
        let timeout = Duration::from_secs(10);
        let start = std::time::Instant::now();
        while !self.socket_path.exists() {
            if start.elapsed() > timeout {
                self.stop()?;
                return Err(ZygoteError::StartFailed(
                    "Timeout waiting for Zygote socket".to_string(),
                ));
            }
            std::thread::sleep(Duration::from_millis(50));
        }

        Ok(())
    }

    #[cfg(not(unix))]
    pub fn start(&mut self, _preload: &[&str]) -> Result<()> {
        Err(ZygoteError::NotSupported)
    }

    /// Stop the Zygote process gracefully
    pub fn stop(&mut self) -> Result<()> {
        if !self.is_running() {
            return Ok(());
        }

        // Try to send shutdown command
        if self.socket_path.exists() {
            let _ = ipc::send_command(&self.socket_path, ipc::ZygoteCommand::Shutdown);
        }

        // Wait for process to exit or kill it
        if let Some(mut child) = self.zygote_process.take() {
            // Give it a moment to shut down gracefully
            std::thread::sleep(Duration::from_millis(100));

            // Check if it's still running
            match child.try_wait() {
                Ok(Some(_)) => {
                    // Already exited
                }
                Ok(None) => {
                    // Still running, kill it
                    let _ = child.kill();
                    let _ = child.wait();
                }
                Err(_) => {
                    // Error checking, try to kill anyway
                    let _ = child.kill();
                }
            }
        }

        // Cleanup socket file
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
    #[cfg(unix)]
    pub fn spawn_worker(&self, script: &Path, args: &[&str]) -> Result<WorkerHandle> {
        if !self.is_running() {
            return Err(ZygoteError::NotRunning);
        }

        // Send FORK command over socket
        let response = ipc::send_command(
            &self.socket_path,
            ipc::ZygoteCommand::Fork {
                script_path: script.to_path_buf(),
                args: args.iter().map(|s| s.to_string()).collect(),
            },
        )?;

        match response {
            ipc::ZygoteResponse::Forked { worker_pid } => Ok(WorkerHandle { pid: worker_pid }),
            ipc::ZygoteResponse::Error { message } => Err(ZygoteError::ForkFailed(message)),
            _ => Err(ZygoteError::ProtocolError(
                "Unexpected response to Fork command".to_string(),
            )),
        }
    }

    #[cfg(not(unix))]
    pub fn spawn_worker(&self, _script: &Path, _args: &[&str]) -> Result<WorkerHandle> {
        Err(ZygoteError::NotSupported)
    }
}

impl Drop for ZygoteLauncher {
    fn drop(&mut self) {
        // Ensure cleanup on drop
        let _ = self.stop();
    }
}
