//! Worker pool management for `velo serve`
//!
//! Manages multiple uvicorn workers with Zygote pre-warming.

use anyhow::Result;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use crate::zygote::ipc;

pub struct Worker {
    pub pid: u32,
    pub port: u16,
    started_at: Instant,
    zygote_socket: PathBuf,
    script_path: Option<PathBuf>,
    /// UDS socket path (RFC-0011 Phase 2)
    pub socket_path: Option<PathBuf>,
}

impl Worker {
    /// Spawn worker via Zygote IPC (UDS mode)
    pub fn spawn_uds_via_zygote(
        zygote_socket: &Path,
        app: &str,
        worker_id: u64,
        shm_file: Option<&std::fs::File>, // Optional SHM file to map
    ) -> Result<Self> {
        Self::validate_app_path(app)?;

        // Architect Recommendation: Use standardized launcher instead of dynamic scripts
        let launcher_path = crate::zygote::find_worker_launcher()
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
                shm_size,
            },
            fd_to_pass,
        )?;

        if let ipc::ZygoteResponse::Forked { worker_pid, .. } = response {
            Ok(Self {
                pid: worker_pid,
                port: 0,
                started_at: Instant::now(),
                zygote_socket: zygote_socket.to_path_buf(),
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
    ) -> Result<Self> {
        Self::validate_app_path(app)?;

        let launcher_path = crate::zygote::find_worker_launcher()
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
                shm_size: None,
            },
            None,
        )?;

        if let ipc::ZygoteResponse::Forked { worker_pid, .. } = response {
            Ok(Self {
                pid: worker_pid,
                port,
                started_at: Instant::now(),
                zygote_socket: zygote_socket.to_path_buf(),
                script_path: None,
                socket_path: None,
            })
        } else {
            anyhow::bail!("Zygote failed to fork worker: {:?}", response);
        }
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

    pub fn pid(&self) -> u32 {
        self.pid
    }

    pub fn uptime(&self) -> Duration {
        self.started_at.elapsed()
    }

    pub fn is_running(&self) -> bool {
        match ipc::send_command(
            &self.zygote_socket,
            ipc::ZygoteCommand::WorkerStatus {
                worker_pid: self.pid,
            },
            None,
        ) {
            Ok(ipc::ZygoteResponse::WorkerInfo { is_running, .. }) => is_running,
            _ => false,
        }
    }

    /// Fast check if worker process exists (no IPC overhead)
    /// Used for health monitoring in the signal loop
    pub fn is_alive(&self) -> bool {
        // Safety: kill with signal 0 checks process existence without sending signal
        // SECURITY: libc::kill(pid, 0) is a standard non-destructive check for process existence.
        unsafe { libc::kill(self.pid as i32, 0) == 0 }
    }

    pub fn shutdown(&self, timeout: Duration) -> Result<()> {
        let _ = ipc::send_command(
            &self.zygote_socket,
            ipc::ZygoteCommand::SignalWorker {
                worker_pid: self.pid,
                signal: 15, // SIGTERM
            },
            None,
        );

        let response = ipc::send_command(
            &self.zygote_socket,
            ipc::ZygoteCommand::WaitWorker {
                worker_pid: self.pid,
                timeout_secs: Some(timeout.as_secs()),
            },
            None,
        );

        match response {
            Ok(ipc::ZygoteResponse::WorkerExited { .. }) => Ok(()),
            _ => {
                let _ = ipc::send_command(
                    &self.zygote_socket,
                    ipc::ZygoteCommand::SignalWorker {
                        worker_pid: self.pid,
                        signal: 9, // SIGKILL
                    },
                    None,
                );
                Ok(())
            }
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
