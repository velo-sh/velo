//! Worker pool management for `velo serve`
//!
//! Manages multiple uvicorn workers with Zygote pre-warming.

use anyhow::Result;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use crate::zygote::core_ipc as ipc;
use uuid::Uuid;

pub struct Worker {
    pub pid: u32,
    pub port: u16,
    started_at: Instant,
    zygote_socket: Option<PathBuf>,
    script_path: Option<PathBuf>,
    /// UDS socket path (RFC-0011 Phase 2)
    pub socket_path: Option<PathBuf>,
}

#[allow(clippy::box_collection)]
fn build_worker_env(
    config: &crate::config::VeloConfig,
) -> Box<std::collections::HashMap<String, String>> {
    // RFC-0012: Always use EnvironmentShield for SSOT environment building.
    // This ensures all workers (Zygote/Direct/Native) are scrubbed identically.
    let shield = crate::lifecycle::v_shield::EnvironmentShield::new(config);
    let mut env = shield.compile_env();

    // Pass additional runtime-specific variables that aren't in the global whitelist
    env.insert("VELO_TRUSTED_PROXY".to_string(), "1".to_string());
    // Gate H (DEF-72-H01): Pass Host PID so workers can validate incoming connections
    env.insert("VELO_HOST_PID".to_string(), std::process::id().to_string());

    if !env.contains_key("VELO_FORWARDED_ALLOW_IPS") {
        env.insert(
            "VELO_FORWARDED_ALLOW_IPS".to_string(),
            "127.0.0.1,::1".to_string(),
        );
    }
    Box::new(env)
}

impl Worker {
    /// Spawn worker via Zygote IPC (UDS mode)
    pub fn spawn_uds_via_zygote(
        zygote_socket: &Path,
        app: &str,
        worker_id: u64,
        shm_file: Option<&std::fs::File>, // Optional SHM file to map
        config: &crate::config::VeloConfig,
        rsgi: bool,
    ) -> Result<Self> {
        Self::validate_app_path(app)?;

        // Architect Recommendation: Use standardized launcher instead of dynamic scripts
        let launcher_path = crate::zygote::find_worker_launcher(config)
            .map_err(|e| anyhow::anyhow!("Zygote launcher error: {}", e))?;

        // 1. Determine a unique UDS path (Industrial Grade - Standardized)
        let socket_path = crate::common::paths::generate_worker_socket_path(worker_id);
        let socket_path_str = socket_path.to_string_lossy().to_string();

        let mut args = vec![
            "--app".to_string(),
            app.to_string(),
            "--uds".to_string(),
            socket_path_str,
            "--proxy-headers".to_string(),
        ];
        if rsgi {
            args.push("--rsgi".to_string());
        }

        let (fd_to_pass, shm_size) = if let Some(file) = shm_file {
            use std::os::unix::prelude::AsRawFd;
            // Get size for the command
            let meta = file.metadata()?;
            (Some(file.as_raw_fd()), Some(meta.len() as usize))
        } else {
            (None, None)
        };

        let response = ipc::send_command(
            zygote_socket,
            ipc::ZygoteCommand::Fork {
                script_path: launcher_path,
                module: None,
                args,
                async_mode: true,
                stdout_path: None,
                stderr_path: None,
                exit_code_path: None,
                fast_mode: false,
                bundle_path: None,
                project_root: None,
                max_bundle_size: None,
                env: build_worker_env(config),
                shm_size,
                request_id: Some(Uuid::now_v7().to_string()),
            },
            fd_to_pass,
        )?;

        if let ipc::ZygoteResponse::Forked { worker_pid, .. } = response {
            Ok(Self {
                pid: worker_pid,
                port: 0,
                started_at: Instant::now(),
                zygote_socket: Some(zygote_socket.to_path_buf()),
                script_path: None,
                socket_path: Some(socket_path),
            })
        } else {
            anyhow::bail!("Zygote failed to fork worker: {:?}", response);
        }
    }

    /// Spawn a worker via Zygote IPC (Legacy TCP mode)
    pub fn spawn_via_zygote(
        zygote_socket: &Path,
        app: &str,
        host: &str,
        port: u16,
        config: &crate::config::VeloConfig,
    ) -> Result<Self> {
        Self::validate_app_path(app)?;

        let launcher_path = crate::zygote::find_worker_launcher(config)
            .map_err(|e| anyhow::anyhow!("Zygote launcher error: {}", e))?;

        let args = vec![
            "--app".to_string(),
            app.to_string(),
            "--host".to_string(),
            host.to_string(),
            "--port".to_string(),
            port.to_string(),
        ];

        let response = ipc::send_command(
            zygote_socket,
            ipc::ZygoteCommand::Fork {
                script_path: launcher_path,
                module: None,
                args,
                async_mode: true,
                stdout_path: None,
                stderr_path: None,
                exit_code_path: None,
                fast_mode: false,
                bundle_path: None,
                project_root: None,
                max_bundle_size: None,
                env: build_worker_env(config),
                shm_size: None,
                request_id: Some(Uuid::now_v7().to_string()),
            },
            None,
        )?;

        if let ipc::ZygoteResponse::Forked { worker_pid, .. } = response {
            Ok(Self {
                pid: worker_pid,
                port,
                started_at: Instant::now(),
                zygote_socket: Some(zygote_socket.to_path_buf()),
                script_path: None,
                socket_path: None,
            })
        } else {
            anyhow::bail!("Zygote failed to fork worker: {:?}", response);
        }
    }

    /// Spawn a worker directly using UDS (Cold-start proxy mode)
    pub fn spawn_uds_direct(
        app: &str,
        worker_id: u64,
        python_path: &Path,
        project_dir: &Path,
        config: &crate::config::VeloConfig,
        rsgi: bool,
    ) -> Result<Self> {
        Self::validate_app_path(app)?;

        let socket_path = crate::common::paths::generate_worker_socket_path(worker_id);
        let socket_path_str = socket_path.to_string_lossy().to_string();

        let mut cmd = std::process::Command::new(python_path);
        cmd.current_dir(project_dir);

        // DEF-72-S02: Clear parent environment to prevent untrusted vars from leaking
        cmd.env_clear();

        // RFC-0012: Surgical Environment Management (§3.1 & §3.5)
        let shield = crate::lifecycle::v_shield::EnvironmentShield::new(config);

        // Phase 7.3: Unified Python Environment Resolution (SSOT) via Shield
        shield
            .apply_with_python(&mut cmd, python_path)
            .map_err(|e| anyhow::anyhow!("Environment shield failure: {}", e))?;

        // Use uvicorn directly if possible, or use RSGI mode
        if rsgi {
            cmd.args([
                "-m",
                "velo_zygote.worker_launcher",
                "--app",
                app,
                "--uds",
                &socket_path_str,
                "--rsgi",
            ]);
        } else {
            cmd.args([
                "-m",
                "uvicorn",
                app,
                "--uds",
                &socket_path_str,
                "--proxy-headers",
            ]);
        }

        let child = cmd
            .spawn()
            .map_err(|e| anyhow::anyhow!("Failed to spawn direct worker: {}", e))?;
        let pid = child.id();

        Ok(Self {
            pid,
            port: 0,
            started_at: Instant::now(),
            zygote_socket: None,
            script_path: None,
            socket_path: Some(socket_path),
        })
    }

    /// Spawn a native Granian worker via fork() [Phase 7.3]
    ///
    /// This method forks the current process and initializes a Granian RSGI worker
    /// in the child. The child process embeds PyO3 and runs the ASGI application
    /// directly in-process.
    #[cfg(unix)]
    pub fn spawn_native(
        app: &str,
        worker_id: i32,
        socket_fd: std::os::unix::io::RawFd,
        python_path: &Path,
        project_dir: &Path,
        _config: &crate::config::VeloConfig,
    ) -> Result<Self> {
        use std::os::unix::process::CommandExt;
        use std::process::Command;

        Self::validate_app_path(app)?;

        // RFC-0019/0025 executive model: Spawn a NEW velo process as the worker
        // This is safe to call from a multi-threaded Host (avoiding fork-safety issues).
        let mut cmd = Command::new(std::env::current_exe()?);
        cmd.arg("worker-native")
            .arg("--worker-id")
            .arg(worker_id.to_string())
            .arg("--fd")
            .arg(socket_fd.to_string())
            .arg("--app")
            .arg(app)
            .arg("--project-dir")
            .arg(project_dir);

        // Security Shield + Sovereignty: Set up Python environment
        // RFC-0012: Always use EnvironmentShield for environment sanitization.
        // REFACTOR: Use shield.apply() to enforce strict whitelist (clears toxins)

        let shield = crate::lifecycle::v_shield::EnvironmentShield::new(_config);
        if let Err(e) = shield.apply(&mut cmd) {
            log::warn!("Security Shield Warning: {}", e);
        }

        // SSOT: Python Environment Configuration
        // =======================================
        // All Python environment detection is centralized in common::python_env
        // This single source of truth is consumed by worker_entry.rs::fixup_python_path()
        match crate::common::python_env::PythonEnv::detect(python_path) {
            Ok(py_env) => {
                py_env.apply_to_command(&mut cmd);
                log::info!(
                    "[SSOT] Python env: base_prefix={:?}, lib_dir={:?}",
                    py_env.base_prefix,
                    py_env.lib_dir
                );
            }
            Err(e) => {
                log::warn!("[SSOT] Failed to detect Python environment: {}", e);
                // Fallback: Set PYTHONHOME from venv parent if possible
                if let Some(venv_root) = python_path.parent().and_then(|p| p.parent()) {
                    cmd.env("VIRTUAL_ENV", venv_root);
                }
            }
        }

        // Also pass the Python executable path for PyO3 to use
        cmd.env("VELO_PYTHON_EXECUTABLE", python_path);

        // Ensure the listener FD is inherited despite FD_CLOEXEC
        unsafe {
            cmd.pre_exec(move || {
                // DEF-72-SEC-001: FD Hygiene - Close all FDs except stdio and the listener
                // This prevents the worker from inheriting sensitive handles (like logs or other sockets)
                #[cfg(target_os = "macos")]
                {
                    // Smart Hygiene: Only close FDs that do NOT have FD_CLOEXEC set.
                    // This protects Rust's internal pipes (which use CLOEXEC) and system handles,
                    // while cleaning up "leaked" user FDs (which lack CLOEXEC).
                    for fd in 3..4096 {
                        if fd == socket_fd {
                            continue;
                        }

                        let flags = libc::fcntl(fd, libc::F_GETFD);
                        if flags != -1 && (flags & libc::FD_CLOEXEC) == 0 {
                            // If CLOEXEC is NOT set, it's a leak candidate. Close it.
                            libc::close(fd);
                        }
                    }
                }

                #[cfg(target_os = "linux")]
                {
                    // Same logic for Linux safety fallback
                    for fd in 3..4096 {
                        if fd == socket_fd {
                            continue;
                        }
                        let flags = libc::fcntl(fd, libc::F_GETFD);
                        if flags != -1 && (flags & libc::FD_CLOEXEC) == 0 {
                            libc::close(fd);
                        }
                    }
                }

                // Ensure the listener FD is explicitly inherited
                // (It might have been closed by the loop if we didn't check, but we did check)
                let flags = libc::fcntl(socket_fd, libc::F_GETFD);
                if flags != -1 {
                    libc::fcntl(socket_fd, libc::F_SETFD, flags & !libc::FD_CLOEXEC);
                }
                Ok(())
            });
        }

        let child = cmd
            .spawn()
            .map_err(|e| anyhow::anyhow!("Failed to spawn native worker: {}", e))?;

        Ok(Self {
            pid: child.id(),
            port: 0,
            started_at: Instant::now(),
            zygote_socket: None,
            script_path: None,
            socket_path: None,
        })
    }

    /// Validate app path security
    fn validate_app_path(app: &str) -> Result<()> {
        if !app.contains(':') {
            anyhow::bail!("Invalid app format: expected 'module:app'");
        }

        let (module, _) = app
            .split_once(':')
            .ok_or_else(|| anyhow::anyhow!("Invalid app format: expected 'module:app'"))?;

        if module.contains("..") {
            anyhow::bail!("Path traversal detected in app: {}", app);
        }

        if module.starts_with('/') {
            anyhow::bail!("Absolute path not allowed in app: {}", app);
        }

        if module.contains('/') {
            let path = std::path::Path::new(module);
            if let Ok(canonical) = path.canonicalize() {
                let canonical_str = canonical.to_string_lossy();
                if canonical_str.contains("..") || canonical_str.starts_with('/') {
                    anyhow::bail!("Symlink points to forbidden path: {}", canonical_str);
                }
            }
        }

        Ok(())
    }

    /// Respawn this worker using its original parameters
    #[allow(clippy::too_many_arguments)]
    pub fn respawn(
        &self,
        app: &str,
        worker_id: u64,
        python_path: &Path,
        project_dir: &Path,
        config: &crate::config::VeloConfig,
        rsgi: bool,
        #[cfg(unix)] socket_fd: Option<std::os::unix::io::RawFd>,
    ) -> Result<Self> {
        if let Some(ref zygote) = self.zygote_socket {
            Self::spawn_uds_via_zygote(zygote, app, worker_id, None, config, rsgi)
        } else if rsgi {
            #[cfg(unix)]
            {
                if let Some(fd) = socket_fd {
                    return Self::spawn_native(
                        app,
                        worker_id as i32,
                        fd,
                        python_path,
                        project_dir,
                        config,
                    );
                }
            }
            Self::spawn_uds_direct(app, worker_id, python_path, project_dir, config, rsgi)
        } else {
            Self::spawn_uds_direct(app, worker_id, python_path, project_dir, config, rsgi)
        }
    }

    pub fn pid(&self) -> u32 {
        self.pid
    }

    pub fn uptime(&self) -> Duration {
        self.started_at.elapsed()
    }

    pub fn is_running(&self) -> bool {
        if let Some(ref zygote) = self.zygote_socket {
            let cmd = ipc::ZygoteCommand::WorkerStatus {
                worker_pid: self.pid,
                request_id: Some(Uuid::now_v7().to_string()),
            };
            match ipc::send_command(zygote, cmd, None) {
                Ok(ipc::ZygoteResponse::WorkerInfo { is_running, .. }) => is_running,
                _ => false,
            }
        } else {
            // Direct worker: check if process exists
            self.is_alive()
        }
    }

    /// Fast check if worker process exists (no IPC overhead)
    /// Used for health monitoring in the signal loop
    ///
    /// RFC-0016: During startup grace period, assume worker is alive to prevent
    /// false-positive death detection before the worker binds its socket.
    pub fn is_alive(&self) -> bool {
        // Grace period: workers get 5 seconds to initialize before liveness checks kick in
        // RFC-0016: Prevent false-positive death detection during startup
        const STARTUP_GRACE_PERIOD: Duration = Duration::from_secs(5);

        // Safety: kill with signal 0 checks process existence without sending signal
        let alive = unsafe { libc::kill(self.pid as i32, 0) == 0 };

        if !alive {
            return false;
        }

        // macOS Technical Debt: Zombies respond to kill(0) with success.
        // If the process is a zombie, it's effectively dead. We try to reap it here
        // to confirm its status.
        #[cfg(target_os = "macos")]
        {
            let mut status = 0;
            let res = unsafe { libc::waitpid(self.pid as i32, &mut status, libc::WNOHANG) };
            if res == self.pid as i32 {
                // Process was a zombie and is now reaped.
                return false;
            }
        }

        if self.started_at.elapsed() < STARTUP_GRACE_PERIOD {
            // During grace period, we don't return false for socket-related issues,
            // but we already handled process death above.
            return true;
        }

        true
    }

    pub fn shutdown(&self, timeout: Duration) -> Result<()> {
        eprintln!(
            "[WORKER] Shutting down worker PID {} (UDS={:?})",
            self.pid, self.socket_path
        );
        if let Some(ref zygote) = self.zygote_socket {
            let cmd = ipc::ZygoteCommand::SignalWorker {
                worker_pid: self.pid,
                signal: 15, // SIGTERM
                request_id: Some(Uuid::now_v7().to_string()),
            };
            let _ = ipc::send_command(zygote, cmd, None);

            let cmd = ipc::ZygoteCommand::WaitWorker {
                worker_pid: self.pid,
                timeout_secs: Some(timeout.as_secs()),
                request_id: Some(Uuid::now_v7().to_string()),
            };
            let response = ipc::send_command(zygote, cmd, None);

            match response {
                Ok(ipc::ZygoteResponse::WorkerExited { .. }) => {
                    eprintln!("[WORKER] PID {} exited gracefully via Zygote", self.pid);
                    Ok(())
                }
                _ => {
                    eprintln!(
                        "[WORKER] PID {} failed graceful Zygote shutdown, triggering fallback",
                        self.pid
                    );
                    // RFC-0012 C.6: Fallback - If Zygote is unreachable or fails to kill,
                    // we MUST perform a direct kill from the Host to ensure eradication.
                    let kill_cmd = ipc::ZygoteCommand::SignalWorker {
                        worker_pid: self.pid,
                        signal: 9, // SIGKILL
                        request_id: Some(Uuid::now_v7().to_string()),
                    };
                    let _ = ipc::send_command(zygote, kill_cmd, None);

                    // Final nuclear fallback: direct kill from Host
                    unsafe {
                        eprintln!(
                            "[WORKER] PID {} NUCLEAR FALLBACK: Direct libc::kill(SIGKILL)",
                            self.pid
                        );
                        let res = libc::kill(self.pid as i32, 9);
                        if res != 0 {
                            let err = std::io::Error::last_os_error();
                            eprintln!(
                                "[WORKER] CRITICAL: libc::kill({}) failed: {}",
                                self.pid, err
                            );
                        } else {
                            eprintln!(
                                "[WORKER] libc::kill({}) returned SUCCESS, waiting for reaping...",
                                self.pid
                            );
                            // Wait up to 1s for reaping
                            let kill_start = Instant::now();
                            while kill_start.elapsed() < Duration::from_secs(1) {
                                let check_res = libc::kill(self.pid as i32, 0);
                                if check_res != 0 {
                                    let err =
                                        std::io::Error::last_os_error().raw_os_error().unwrap_or(0);
                                    if err == libc::ESRCH {
                                        eprintln!("[WORKER] PID {} reaped (ESRCH)!", self.pid);
                                        break;
                                    }
                                    // If EPERM, process still exists!
                                }
                                std::thread::sleep(Duration::from_millis(100));
                            }
                        }
                    }
                    Ok(())
                }
            }
        } else {
            // Direct worker: signal directly
            eprintln!(
                "[WORKER] PID {} direct shutdown sequence initiated",
                self.pid
            );
            unsafe {
                libc::kill(self.pid as i32, 15); // SIGTERM
            }
            // Wait for exit or kill
            let start = Instant::now();
            while start.elapsed() < timeout {
                if !self.is_alive() {
                    eprintln!("[WORKER] PID {} died after SIGTERM", self.pid);
                    return Ok(());
                }
                std::thread::sleep(Duration::from_millis(100));
            }
            unsafe {
                eprintln!("[WORKER] PID {} SIGTERM timeout, sending SIGKILL", self.pid);
                libc::kill(self.pid as i32, 9);
            }
            Ok(())
        }
    }
}

impl Drop for Worker {
    fn drop(&mut self) {
        // RFC-0012 C.6: RAII Cleanup - Ensure worker process is terminated when handle is dropped
        // We use a 2s timeout for graceful shutdown before SIGKILL
        let _ = self.shutdown(Duration::from_secs(2));

        if let Some(ref path) = self.script_path {
            let _ = std::fs::remove_file(path);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_validate_app_path_valid() {
        assert!(Worker::validate_app_path("main:app").is_ok());
        assert!(Worker::validate_app_path("myapp.main:create_app").is_ok());
    }

    #[test]
    fn test_validate_app_path_invalid() {
        assert!(Worker::validate_app_path("../evil:app").is_err());
        assert!(Worker::validate_app_path("/etc/passwd:data").is_err());
        assert!(Worker::validate_app_path("nocolon").is_err());
    }
}
