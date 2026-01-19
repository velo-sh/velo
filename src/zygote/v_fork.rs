//! v_fork.rs - Fork lifecycle management (RFC-0028 §10.3.1)
//!
//! This module handles worker process spawning and lifecycle management.
//! Aligned with Python: velo_zygote/v_fork.py

use crate::config::VeloConfig;
use crate::zygote::core_ipc;
use crate::zygote::error::{Result, ZygoteError};
use std::collections::HashMap;
use std::path::{Path, PathBuf};

/// Get worker timeout from config
fn get_worker_timeout_secs() -> u64 {
    VeloConfig::from_env_only().zygote_socket_timeout
}

/// Handle to a spawned worker process
pub struct WorkerHandle {
    pid: u32,
    stdout_path: Option<PathBuf>,
    stderr_path: Option<PathBuf>,
    exit_code_path: Option<PathBuf>,
}

impl WorkerHandle {
    /// Create a new WorkerHandle
    pub fn new(
        pid: u32,
        stdout_path: Option<PathBuf>,
        stderr_path: Option<PathBuf>,
        exit_code_path: Option<PathBuf>,
    ) -> Self {
        Self {
            pid,
            stdout_path,
            stderr_path,
            exit_code_path,
        }
    }

    /// Wait for the worker to complete with 30s timeout (DEF-P3-012)
    /// We detect completion by waiting for the exit_code file to appear.
    /// If timeout expires, we kill the worker process.
    #[cfg(unix)]
    pub fn wait(&self) -> Result<i32> {
        let start = std::time::Instant::now();
        let timeout_secs = get_worker_timeout_secs();
        let timeout = std::time::Duration::from_secs(timeout_secs);

        // Wait for exit_code file to exist (worker writes it when done)
        let mut timed_out = false;
        if let Some(ref path) = self.exit_code_path {
            // Poll for file existence with fast checks
            loop {
                if path.exists() {
                    // File exists - script completed
                    break;
                }

                // Check timeout
                if start.elapsed() > timeout {
                    timed_out = true;
                    eprintln!(
                        "⏱️ Worker {} timed out after {}s, killing...",
                        self.pid, timeout_secs
                    );
                    // Kill the worker process
                    unsafe {
                        libc::kill(self.pid as i32, libc::SIGKILL);
                    }
                    break;
                }

                // Fast polling (10ms floor) ensures low latency while reducing log volume.
                std::thread::sleep(std::time::Duration::from_millis(10));
            }
        }

        // Flush stdout and stderr files to real stdout/stderr
        self.flush_stdout();
        self.flush_stderr();

        // Read exit code from file (DEF-P3-013/014)
        let exit_code = self.read_exit_code();

        // Return timeout exit code if timed out
        if timed_out {
            Ok(124) // Standard timeout exit code
        } else {
            Ok(exit_code)
        }
    }

    #[cfg(not(unix))]
    pub fn wait(&self) -> Result<i32> {
        // Windows: not supported
        Ok(0)
    }

    /// Flush captured stdout from tempfile to real stdout
    #[allow(clippy::collapsible_if)]
    fn flush_stdout(&self) {
        if let Some(ref path) = self.stdout_path {
            if path.exists() {
                if let Ok(contents) = std::fs::read_to_string(path) {
                    if !contents.is_empty() {
                        print!("{}", contents);
                        use std::io::Write;
                        let _ = std::io::stdout().flush();
                    }
                }
                let _ = std::fs::remove_file(path);
            }
        }
    }

    /// Flush captured stderr from tempfile to real stderr
    #[allow(clippy::collapsible_if)]
    fn flush_stderr(&self) {
        if let Some(ref path) = self.stderr_path {
            if path.exists() {
                if let Ok(contents) = std::fs::read_to_string(path) {
                    if !contents.is_empty() {
                        eprint!("{}", contents);
                        use std::io::Write;
                        let _ = std::io::stderr().flush();
                    }
                }
                let _ = std::fs::remove_file(path);
            }
        }
    }

    /// Read exit code from tempfile (DEF-P3-013/014)
    #[allow(clippy::collapsible_if)]
    fn read_exit_code(&self) -> i32 {
        if let Some(ref path) = self.exit_code_path {
            if path.exists() {
                if let Ok(contents) = std::fs::read_to_string(path) {
                    let _ = std::fs::remove_file(path);
                    if let Ok(code) = contents.trim().parse::<i32>() {
                        return code;
                    }
                }
            }
        }
        0 // Default to 0 if no exit code file
    }

    /// Get the worker's PID
    pub fn pid(&self) -> u32 {
        self.pid
    }

    /// Get path to captured stdout
    pub fn stdout_path(&self) -> Option<&PathBuf> {
        self.stdout_path.as_ref()
    }

    /// Get path to captured stderr
    pub fn stderr_path(&self) -> Option<&PathBuf> {
        self.stderr_path.as_ref()
    }
}

/// Fork a new worker from the Zygote
///
/// This is the primary interface for spawning worker processes via the Zygote.
/// It communicates with the Zygote over IPC and returns a handle to the spawned worker.
#[cfg(unix)]
#[allow(clippy::too_many_arguments)]
pub fn spawn_worker(
    socket_path: &Path,
    script: &Path,
    args: &[&str],
    async_mode: bool,
    fast_mode: bool,
    bundle_path: Option<PathBuf>,
    project_root: Option<PathBuf>,
    max_bundle_size: Option<u64>,
    shm_file: Option<&std::fs::File>,
    env_overrides: Option<HashMap<String, String>>,
    config: &VeloConfig,
) -> Result<WorkerHandle> {
    // Canonicalize script path - Zygote may have different CWD
    let script_path = if script.is_absolute() {
        script.to_path_buf()
    } else {
        std::env::current_dir()
            .map(|cwd| cwd.join(script))
            .unwrap_or_else(|_| script.to_path_buf())
    };

    // Create tempfiles for I/O capture (use CLI PID + timestamp for uniqueness)
    let timestamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let pid = std::process::id();

    let stdout_path = std::env::temp_dir().join(format!("velo-out-{}-{}.tmp", pid, timestamp));
    let stderr_path = std::env::temp_dir().join(format!("velo-err-{}-{}.tmp", pid, timestamp));
    let exit_code_path = std::env::temp_dir().join(format!("velo-exit-{}-{}.tmp", pid, timestamp));

    let (fd_to_pass, shm_size) = if let Some(file) = shm_file {
        use std::os::unix::io::AsRawFd;
        let meta = file
            .metadata()
            .map_err(|e| ZygoteError::IOError(e.to_string()))?;
        (Some(file.as_raw_fd()), Some(meta.len() as usize))
    } else {
        (None, None)
    };

    // Send FORK command over socket
    log::debug!(
        "[spawn_worker] Sending Fork command to socket: {:?}",
        socket_path
    );
    log::debug!("[spawn_worker] Socket exists: {}", socket_path.exists());
    let response = core_ipc::send_command(
        socket_path,
        core_ipc::ZygoteCommand::Fork {
            script_path,
            args: args.iter().map(|s| s.to_string()).collect(),
            async_mode,
            stdout_path: Some(stdout_path.clone()),
            stderr_path: Some(stderr_path.clone()),
            exit_code_path: Some(exit_code_path.clone()),
            fast_mode,
            bundle_path,
            project_root,
            max_bundle_size,
            env: {
                let mut base_env = crate::lifecycle::EnvironmentShield::new(config).compile_env();
                if let Some(overrides) = env_overrides {
                    for (k, v) in overrides {
                        base_env.insert(k, v);
                    }
                }
                Box::new(base_env)
            },
            shm_size,
            request_id: Some(uuid::Uuid::now_v7().to_string()),
        },
        fd_to_pass,
    )?;

    match response {
        core_ipc::ZygoteResponse::Forked {
            worker_pid,
            exit_code,
        } => {
            // If we have an exit code already (sync mode), we can write it to the temp file
            // to reuse the existing WorkerHandle::wait() logic or just handle it here.
            #[allow(clippy::collapsible_if)]
            if let Some(code) = exit_code {
                if let Err(e) = std::fs::write(&exit_code_path, code.to_string()) {
                    eprintln!("⚠️ Failed to write premature exit code: {}", e);
                }
            }

            Ok(WorkerHandle::new(
                worker_pid,
                Some(stdout_path),
                Some(stderr_path),
                Some(exit_code_path),
            ))
        }
        core_ipc::ZygoteResponse::Error { message } => Err(ZygoteError::ForkFailed(message)),
        _ => Err(ZygoteError::ProtocolError(
            "Unexpected response to Fork command".to_string(),
        )),
    }
}

#[cfg(not(unix))]
#[allow(clippy::too_many_arguments)]
pub fn spawn_worker(
    _socket_path: &Path,
    _script: &Path,
    _args: &[&str],
    _async_mode: bool,
    _fast_mode: bool,
    _bundle_path: Option<PathBuf>,
    _project_root: Option<PathBuf>,
    _max_bundle_size: Option<u64>,
    _shm_file: Option<&std::fs::File>,
    _env_overrides: Option<HashMap<String, String>>,
    _config: &VeloConfig,
) -> Result<WorkerHandle> {
    Err(ZygoteError::NotSupported)
}
