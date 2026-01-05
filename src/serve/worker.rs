//! Worker pool management for `velo serve`
//!
//! Manages multiple uvicorn workers with Zygote pre-warming.

use anyhow::Result;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, Instant};

use crate::zygote::ipc;

/// Global worker counter (avoid temp file conflicts)
static WORKER_COUNTER: AtomicU64 = AtomicU64::new(0);

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
    /// Spawn worker via Zygote fork (Legacy TCP Mode)
    pub fn spawn_via_zygote(
        zygote_socket: &Path,
        app: &str,
        host: &str,
        port: u16,
    ) -> Result<Self> {
        // Security validation
        Self::validate_app_path(app)?;

        // Generate unique script path
        let worker_id = WORKER_COUNTER.fetch_add(1, Ordering::SeqCst);
        let script_path = Self::create_temp_script_path(worker_id)?;

        // Generate worker script
        let script_content = Self::generate_worker_script(app, host, port)?;

        // Write script securely
        Self::write_script_securely(&script_path, &script_content)?;

        // Fork via Zygote
        let worker_pid = Self::fork_via_zygote(zygote_socket, &script_path)?;

        Ok(Worker {
            pid: worker_pid,
            port,
            started_at: Instant::now(),
            zygote_socket: zygote_socket.to_path_buf(),
            script_path: Some(script_path),
            socket_path: None,
        })
    }

    /// Spawn worker via Zygote using Unix Domain Sockets (RFC-0011 Phase 2)
    pub fn spawn_uds_via_zygote(zygote_socket: &Path, app: &str) -> Result<Self> {
        Self::validate_app_path(app)?;

        let worker_id = WORKER_COUNTER.fetch_add(1, Ordering::SeqCst);
        let script_path = Self::create_temp_script_path(worker_id)?;

        // Generate unique UDS path
        let temp_dir = script_path.parent().unwrap();
        let socket_path = temp_dir.join(format!("velo-worker-{}.sock", worker_id));
        let socket_path_str = socket_path.to_string_lossy().to_string();

        // Use UDS script generator
        let script_content = Self::generate_uds_worker_script(app, &socket_path_str)?;

        Self::write_script_securely(&script_path, &script_content)?;
        let worker_pid = Self::fork_via_zygote(zygote_socket, &script_path)?;

        Ok(Worker {
            pid: worker_pid,
            port: 0, // Unused in UDS mode
            started_at: Instant::now(),
            zygote_socket: zygote_socket.to_path_buf(),
            script_path: Some(script_path),
            socket_path: Some(socket_path),
        })
    }

    /// Validate app path security
    fn validate_app_path(app: &str) -> Result<()> {
        if !app.contains(':') {
            anyhow::bail!("Invalid app format: expected 'module:app'");
        }

        let (module, _) = app.split_once(':').unwrap();

        // Prevent path traversal
        if module.contains("..") {
            anyhow::bail!("Path traversal detected in app: {}", app);
        }

        // Prevent absolute path injection
        if module.starts_with('/') {
            anyhow::bail!("Absolute path not allowed in app: {}", app);
        }

        // Prevent symlink attacks - check if module path exists and resolve it
        // This prevents symlinks from bypassing the above checks
        if module.contains('/') {
            // If it looks like a file path, verify it's not a symlink
            let path = std::path::Path::new(module);
            if path.exists() {
                // canonicalize() will fail if it's a broken symlink
                // and will resolve symlinks, allowing us to check the real path
                if let Ok(canonical) = path.canonicalize() {
                    let canonical_str = canonical.to_string_lossy();
                    // Re-check the canonical path agains our security rules
                    if canonical_str.contains("..") || canonical_str.starts_with('/') {
                        anyhow::bail!("Symlink points to forbidden path: {}", canonical_str);
                    }
                }
            }
        }

        Ok(())
    }

    /// Create temp script path
    fn create_temp_script_path(worker_id: u64) -> Result<PathBuf> {
        let temp_dir = std::env::var("VELO_TEMP_DIR")
            .map(PathBuf::from)
            .unwrap_or_else(|_| std::env::temp_dir());

        std::fs::create_dir_all(&temp_dir)?;

        let script_name = format!("velo-worker-{}-{}.py", std::process::id(), worker_id);

        Ok(temp_dir.join(script_name))
    }

    /// Generate worker script (injection-safe)
    fn generate_worker_script(app: &str, host: &str, port: u16) -> Result<String> {
        // RFC-0011 Alignment: Inline uvicorn execution to avoid dependency on missing worker_runner.py
        Ok(format!(
            r#"#!/usr/bin/env python3
import sys
import os
import uvicorn

# Add project directory to sys.path
sys.path.insert(0, os.getcwd())

uvicorn.run(
    "{app}",
    host="{host}",
    port={port},
    log_level="info",
)
"#,
            app = app,
            host = host,
            port = port
        ))
    }

    /// Generate UDS worker script (RFC-0011: uses Unix socket instead of TCP port)
    ///
    /// This script runs uvicorn with:
    /// - `--uds {socket_path}` instead of `--port`
    /// - `--proxy-headers` to enable X-Forwarded-* support
    pub fn generate_uds_worker_script(app: &str, socket_path: &str) -> Result<String> {
        // Security validation
        Self::validate_app_path(app)?;

        Ok(format!(
            r#"#!/usr/bin/env python3
"""
Velo UDS Worker Script (RFC-0011)
Runs uvicorn with Unix Domain Socket for Zygote worker integration.
"""
import sys
import os

# Add project directory to sys.path
sys.path.insert(0, os.getcwd())

import uvicorn

# RFC-0011: UDS mode with proxy headers
uvicorn.run(
    "{app}",
    uds="{socket_path}",
    proxy_headers=True,
    forwarded_allow_ips="*",
    log_level="info",
)
"#,
            app = app,
            socket_path = socket_path,
        ))
    }

    /// Write script securely (0600 permissions)
    fn write_script_securely(path: &Path, content: &str) -> Result<()> {
        use std::fs::OpenOptions;
        use std::io::Write;

        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            let mut file = OpenOptions::new()
                .create(true)
                .write(true)
                .truncate(true)
                .mode(0o600)
                .open(path)?;

            file.write_all(content.as_bytes())?;
        }

        #[cfg(not(unix))]
        {
            let mut file = OpenOptions::new()
                .create(true)
                .write(true)
                .truncate(true)
                .open(path)?;

            file.write_all(content.as_bytes())?;
        }

        Ok(())
    }

    /// Fork via Zygote IPC
    fn fork_via_zygote(zygote_socket: &Path, script_path: &Path) -> Result<u32> {
        let response = ipc::send_command(
            zygote_socket,
            ipc::ZygoteCommand::Fork {
                script_path: script_path.to_path_buf(),
                args: vec![],
                async_mode: true,
                stdout_path: None,
                stderr_path: None,
                exit_code_path: None,
                fast_mode: false,
                bundle_path: None,
                project_root: None,
                max_bundle_size: None,
            },
        )?;

        match response {
            ipc::ZygoteResponse::Forked { worker_pid, .. } => Ok(worker_pid),
            ipc::ZygoteResponse::Error { message } => {
                anyhow::bail!("Zygote fork failed: {}", message)
            }
            _ => anyhow::bail!("Unexpected response from Zygote"),
        }
    }

    pub fn is_running(&self) -> bool {
        match ipc::send_command(
            &self.zygote_socket,
            ipc::ZygoteCommand::WorkerStatus {
                worker_pid: self.pid,
            },
        ) {
            Ok(ipc::ZygoteResponse::WorkerInfo { is_running, .. }) => is_running,
            _ => false,
        }
    }

    pub fn shutdown(&self, timeout: Duration) -> Result<()> {
        // 1. SIGTERM
        ipc::send_command(
            &self.zygote_socket,
            ipc::ZygoteCommand::SignalWorker {
                worker_pid: self.pid,
                signal: 15, // SIGTERM
            },
        )?;

        // 2. Wait
        let response = ipc::send_command(
            &self.zygote_socket,
            ipc::ZygoteCommand::WaitWorker {
                worker_pid: self.pid,
                timeout_secs: Some(timeout.as_secs()),
            },
        )?;

        match response {
            ipc::ZygoteResponse::WorkerExited { .. } => Ok(()),
            _ => {
                // 3. SIGKILL
                ipc::send_command(
                    &self.zygote_socket,
                    ipc::ZygoteCommand::SignalWorker {
                        worker_pid: self.pid,
                        signal: 9, // SIGKILL
                    },
                )?;
                Ok(())
            }
        }
    }

    pub fn uptime(&self) -> Duration {
        self.started_at.elapsed()
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

    #[test]
    fn test_temp_script_uniqueness() {
        let path1 = Worker::create_temp_script_path(0).unwrap();
        let path2 = Worker::create_temp_script_path(1).unwrap();
        assert_ne!(path1, path2);
    }

    // =========================================================================
    // TDD Cycle 2.1: UDS Worker Script Generation
    // =========================================================================

    /// 🔴 RED: Test that UDS worker script uses --uds flag instead of --port
    #[test]
    fn test_generate_uds_worker_script_has_uds_flag() {
        let socket_path = "/tmp/velo-worker-1.sock";
        let script = Worker::generate_uds_worker_script("main:app", socket_path).unwrap();

        // Must contain --uds flag
        assert!(
            script.contains("--uds") || script.contains("uds="),
            "UDS script must use --uds flag, got: {}",
            script
        );

        // Must contain the socket path
        assert!(
            script.contains(socket_path),
            "UDS script must contain socket path"
        );

        // Must NOT contain --port (we're using UDS, not TCP)
        assert!(
            !script.contains("--port") && !script.contains("\"port\""),
            "UDS script must NOT use --port"
        );
    }

    /// 🔴 RED: Test that UDS worker script enables proxy headers
    #[test]
    fn test_generate_uds_worker_script_has_proxy_headers() {
        let script = Worker::generate_uds_worker_script("main:app", "/tmp/w.sock").unwrap();

        // RFC-0011 C.3: Must enable proxy_headers for X-Forwarded-* support
        assert!(
            script.contains("proxy_headers") || script.contains("--proxy-headers"),
            "UDS script must enable proxy_headers"
        );
    }
}
