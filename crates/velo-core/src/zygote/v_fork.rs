//! v_fork.rs - Fork lifecycle management (RFC-0028 §10.3.1)
//!
//! This module handles worker process spawning and lifecycle management.
//! Aligned with Python: velo_zygote/v_fork.py

use crate::config::VeloConfig;
use crate::zygote::error::{Result, ZygoteError};
use crate::zygote::{ZygoteCircuitBreaker, core_ipc};
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
    module: Option<String>,
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

    // Check Circuit Breaker (RFC-0036)
    if ZygoteCircuitBreaker::is_tripped(config) {
        log::warn!("🚧 Zygote Circuit Breaker is OPEN. Fallback to direct spawn.");
        return spawn_direct(
            &script_path,
            module,
            args,
            stdout_path,
            stderr_path,
            exit_code_path,
            env_overrides,
            config,
        );
    }

    // Send FORK command over socket
    log::debug!(
        "[spawn_worker] Sending Fork command to socket: {:?}",
        socket_path
    );
    log::debug!("[spawn_worker] Socket exists: {}", socket_path.exists());

    let start_time = std::time::Instant::now();
    let response_result = core_ipc::send_command(
        socket_path,
        core_ipc::ZygoteCommand::Fork {
            script_path: script_path.clone(),
            module: module.clone(),
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
                if let Some(overrides) = env_overrides.clone() {
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
    );

    let response = match response_result {
        Ok(resp) => {
            ZygoteCircuitBreaker::record_success();
            resp
        }
        Err(e) => {
            log::error!(
                "❌ Zygote IPC failure: {}. Recording failure for Circuit Breaker.",
                e
            );
            ZygoteCircuitBreaker::record_failure(config);
            if ZygoteCircuitBreaker::is_tripped(config) {
                log::warn!("🔄 Emergency fallback to direct spawn after Zygote failure.");
                return spawn_direct(
                    &script_path,
                    module,
                    args,
                    stdout_path,
                    stderr_path,
                    exit_code_path,
                    env_overrides,
                    config,
                );
            }
            return Err(e);
        }
    };

    // SLO: Error Budget Policy (Fork Latency)
    let elapsed = start_time.elapsed();
    let elapsed_ms = elapsed.as_millis() as u64;

    // We only check SLO if fork succeeded (otherwise it's an error, handled elsewhere)
    if let core_ipc::ZygoteResponse::Forked { worker_pid, .. } = &response {
        if config.metrics_enabled && elapsed_ms >= config.slo_fork_latency_ms {
            log::warn!(
                "⚠️ SLO Violation: Fork latency {}ms > {}ms (PID: {})",
                elapsed_ms,
                config.slo_fork_latency_ms,
                worker_pid
            );
        } else if config.metrics_enabled {
            log::debug!("✅ Fork latency {}ms (PID: {})", elapsed_ms, worker_pid);
        }
    }

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

/// Fallback mechanism: Spawn worker directly via standard process (P2-001)
#[allow(clippy::too_many_arguments)]
fn spawn_direct(
    script: &Path,
    module: Option<String>,
    args: &[&str],
    stdout_path: PathBuf,
    stderr_path: PathBuf,
    exit_code_path: PathBuf,
    env_overrides: Option<HashMap<String, String>>,
    config: &VeloConfig,
) -> Result<WorkerHandle> {
    use std::process::{Command, Stdio};

    let python = crate::python::detect_python(Path::new("."))
        .map_err(|e| ZygoteError::IOError(format!("Python detection failed: {}", e)))?;

    let mut cmd = Command::new(python);

    if let Some(m) = module {
        cmd.arg("-m").arg(m);
    } else {
        cmd.arg(script);
    }

    for arg in args {
        cmd.arg(arg);
    }

    // Apply shielded environment
    let mut base_env = crate::lifecycle::EnvironmentShield::new(config).compile_env();
    if let Some(overrides) = env_overrides {
        for (k, v) in overrides {
            base_env.insert(k, v);
        }
    }
    cmd.envs(base_env);

    // Redirect IO to temp files for compatibility with WorkerHandle
    let stdout_file = std::fs::File::create(&stdout_path)
        .map_err(|e| ZygoteError::IOError(format!("Failed to create stdout file: {}", e)))?;
    let stderr_file = std::fs::File::create(&stderr_path)
        .map_err(|e| ZygoteError::IOError(format!("Failed to create stderr file: {}", e)))?;

    cmd.stdout(Stdio::from(stdout_file));
    cmd.stderr(Stdio::from(stderr_file));

    let child = cmd
        .spawn()
        .map_err(|e| ZygoteError::ForkFailed(format!("Direct spawn failed: {}", e)))?;

    let pid = child.id();

    // Spawn a thread to wait for the child and write the exit code
    // This maintains the WorkerHandle::wait() contract.
    let exit_path_clone = exit_code_path.clone();
    std::thread::spawn(move || {
        let mut child = child;
        if let Ok(status) = child.wait() {
            let code = status.code().unwrap_or(0);
            let _ = std::fs::write(&exit_path_clone, code.to_string());
        }
    });

    Ok(WorkerHandle::new(
        pid,
        Some(stdout_path),
        Some(stderr_path),
        Some(exit_code_path),
    ))
}

/// Fork a new worker via an existing Zygote stream
#[cfg(unix)]
#[allow(clippy::too_many_arguments)]
pub fn spawn_worker_via_stream(
    zygote_stream: &mut crate::zygote::core_ipc::ZygoteStream,
    script: &Path,
    module: Option<String>,
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
    // Canonicalize script path
    let script_path = if script.is_absolute() {
        script.to_path_buf()
    } else {
        std::env::current_dir()
            .map(|cwd| cwd.join(script))
            .unwrap_or_else(|_| script.to_path_buf())
    };

    // Create tempfiles for I/O capture
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

    let start_time = std::time::Instant::now();

    let request = core_ipc::ZygoteCommand::Fork {
        script_path: script_path.clone(),
        module: module.clone(),
        args: args.iter().map(|s| s.to_string()).collect(),
        async_mode,
        stdout_path: Some(stdout_path.clone()),
        stderr_path: Some(stderr_path.clone()),
        exit_code_path: Some(exit_code_path.clone()),
        fast_mode,
        bundle_path,
        project_root: project_root.clone(),
        max_bundle_size,
        env: {
            let mut base_env = crate::lifecycle::EnvironmentShield::new(config).compile_env();
            if let Some(overrides) = env_overrides.clone() {
                for (k, v) in overrides {
                    base_env.insert(k, v);
                }
            }
            // Transition: Ensure VIRTUAL_ENV is passed for auto-discovery
            if let Some(ref pr) = project_root {
                base_env.insert(
                    "VIRTUAL_ENV".to_string(),
                    pr.join(".venv").to_string_lossy().to_string(),
                );
            }
            Box::new(base_env)
        },
        shm_size,
        request_id: Some(uuid::Uuid::now_v7().to_string()),
    };

    let response = match zygote_stream.send_command(&request, fd_to_pass) {
        Ok(resp) => {
            ZygoteCircuitBreaker::record_success();
            resp
        }
        Err(e) => {
            log::error!("❌ Zygote Stream IPC failure: {}", e);
            ZygoteCircuitBreaker::record_failure(config);
            return Err(e);
        }
    };

    // SLO checking logic...
    let elapsed_ms = start_time.elapsed().as_millis() as u64;
    if let core_ipc::ZygoteResponse::Forked { worker_pid, .. } = &response {
        #[allow(clippy::collapsible_if)]
        if config.metrics_enabled && elapsed_ms >= config.slo_fork_latency_ms {
            log::warn!(
                "⚠️ SLO Violation: Fork latency {}ms > {}ms (PID: {})",
                elapsed_ms,
                config.slo_fork_latency_ms,
                worker_pid
            );
        }
    }

    match response {
        core_ipc::ZygoteResponse::Forked {
            worker_pid,
            exit_code,
        } => {
            if let Some(code) = exit_code {
                let _ = std::fs::write(&exit_code_path, code.to_string());
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
    _socket_path: &std::path::Path,
    _script: &std::path::Path,
    _module: Option<String>,
    _args: &[&str],
    _async_mode: bool,
    _fast_mode: bool,
    _bundle_path: Option<std::path::PathBuf>,
    _project_root: Option<std::path::PathBuf>,
    _max_bundle_size: Option<u64>,
    _shm_file: Option<&std::fs::File>,
    _env_overrides: Option<std::collections::HashMap<String, String>>,
    _config: &crate::config::VeloConfig,
) -> Result<WorkerHandle> {
    Err(ZygoteError::NotSupported)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_circuit_breaker_persistence() {
        let dir = tempdir().unwrap();
        let socket_dir = dir.path().to_path_buf();
        unsafe {
            std::env::set_var("VELO_SOCKET_DIR", socket_dir.to_str().unwrap());
        }

        let config = VeloConfig {
            circuit_breaker_enabled: true,
            circuit_breaker_threshold: 2,
            ..Default::default()
        };

        // Verify initial state
        assert!(!ZygoteCircuitBreaker::is_tripped(&config));

        // Record first failure
        ZygoteCircuitBreaker::record_failure(&config);
        assert!(!ZygoteCircuitBreaker::is_tripped(&config));

        // Record second failure (should trip)
        ZygoteCircuitBreaker::record_failure(&config);
        assert!(ZygoteCircuitBreaker::is_tripped(&config));

        // Verify it persists on disk (simulate new process by checking again)
        assert!(ZygoteCircuitBreaker::is_tripped(&config));

        // Record success (should reset)
        ZygoteCircuitBreaker::record_success();
        assert!(!ZygoteCircuitBreaker::is_tripped(&config));

        unsafe {
            std::env::remove_var("VELO_SOCKET_DIR");
        }
    }
}
