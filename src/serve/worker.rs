//! Worker pool management for `velo serve`
//!
//! Manages multiple uvicorn workers with Zygote pre-warming.

use anyhow::Result;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use crate::zygote::ipc;
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
    let mut env = std::env::vars()
        .filter(|(k, _)| config.security_env_whitelist.contains(k))
        .collect::<std::collections::HashMap<String, String>>();
    env.insert("VELO_TRUSTED_PROXY".to_string(), "1".to_string());
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
    ) -> Result<Self> {
        Self::validate_app_path(app)?;

        // Architect Recommendation: Use standardized launcher instead of dynamic scripts
        let launcher_path = crate::zygote::find_worker_launcher(config)
            .map_err(|e| anyhow::anyhow!("Zygote launcher error: {}", e))?;

        // 1. Determine a unique UDS path (Industrial Grade - Standardized)
        let socket_path = crate::common::paths::generate_worker_socket_path(worker_id);
        let socket_path_str = socket_path.to_string_lossy().to_string();

        let args = vec![
            "--app".to_string(),
            app.to_string(),
            "--uds".to_string(),
            socket_path_str,
            "--proxy-headers".to_string(),
        ];

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
    ) -> Result<Self> {
        Self::validate_app_path(app)?;

        let socket_path = crate::common::paths::generate_worker_socket_path(worker_id);
        let socket_path_str = socket_path.to_string_lossy().to_string();

        let mut cmd = std::process::Command::new(python_path);
        cmd.current_dir(project_dir);

        // Pass essential environment (Surgical Whitelist - RFC-0012)

        let env = build_worker_env(config);
        for (k, v) in env.iter() {
            cmd.env(k, v);
        }

        // Use uvicorn directly if possible, or fall back to velo-managed launcher
        cmd.args([
            "-m",
            "uvicorn",
            app,
            "--uds",
            &socket_path_str,
            "--proxy-headers",
        ]);

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
    pub fn respawn(
        &self,
        app: &str,
        worker_id: u64,
        python_path: &Path,
        project_dir: &Path,
        config: &crate::config::VeloConfig,
    ) -> Result<Self> {
        if let Some(ref zygote) = self.zygote_socket {
            Self::spawn_uds_via_zygote(zygote, app, worker_id, None, config)
        } else {
            Self::spawn_uds_direct(app, worker_id, python_path, project_dir, config)
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
        const STARTUP_GRACE_PERIOD: Duration = Duration::from_secs(5);

        if self.started_at.elapsed() < STARTUP_GRACE_PERIOD {
            // During grace period, only check if process still exists
            // Don't trigger respawn logic even if socket isn't ready
            return unsafe { libc::kill(self.pid as i32, 0) == 0 };
        }

        // After grace period, normal liveness check
        // Safety: kill with signal 0 checks process existence without sending signal
        // SECURITY: libc::kill(pid, 0) is a standard non-destructive check for process existence.
        unsafe { libc::kill(self.pid as i32, 0) == 0 }
    }

    pub fn shutdown(&self, timeout: Duration) -> Result<()> {
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
                Ok(ipc::ZygoteResponse::WorkerExited { .. }) => Ok(()),
                _ => {
                    let kill_cmd = ipc::ZygoteCommand::SignalWorker {
                        worker_pid: self.pid,
                        signal: 9, // SIGKILL
                        request_id: Some(Uuid::now_v7().to_string()),
                    };
                    let _ = ipc::send_command(zygote, kill_cmd, None);
                    Ok(())
                }
            }
        } else {
            // Direct worker: signal directly
            unsafe {
                libc::kill(self.pid as i32, 15); // SIGTERM
            }
            // Wait for exit or kill
            let start = Instant::now();
            while start.elapsed() < timeout {
                if !self.is_alive() {
                    return Ok(());
                }
                std::thread::sleep(Duration::from_millis(100));
            }
            unsafe {
                libc::kill(self.pid as i32, 9); // SIGKILL
            }
            Ok(())
        }
    }
}

impl Drop for Worker {
    fn drop(&mut self) {
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
