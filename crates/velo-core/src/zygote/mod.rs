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
pub mod circuit_breaker;
pub mod cli;
pub mod core_ipc;
pub mod error;
pub mod guardian;
pub mod peer_check;
pub mod v_fork;

pub use circuit_breaker::ZygoteCircuitBreaker;

// Re-export v_fork types for backward compatibility (RFC-0028 §10.3.5)
pub use v_fork::{WorkerHandle, spawn_worker};

extern crate log;

use crate::common::paths::VeloPaths;
use crate::config::VeloConfig;
use crate::custody::EnvironmentSync;
use crate::lifecycle::{Airlock, EnvironmentShield};
use crate::zygote::core_ipc::ZygoteResponse;
use crate::zygote::error::{Result, ZygoteError};
use std::fs::{self, OpenOptions};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::Duration;

/// The Zero-Dependency Bootstrap Shim for V3 (RFC-0012)
const BOOTSTRAP_PY: &str = include_str!("bootstrap.py");

/// Worker execution timeout in seconds
/// Long-running scripts may need a higher value; configurable is planned
pub const WORKER_TIMEOUT_SECS: u64 = 30;

/// Socket startup timeout in seconds
/// CI environments may need a higher value (increased from 10 to 30 for GitHub Actions)
pub const SOCKET_STARTUP_TIMEOUT_SECS: u64 = 30;

/// Check if Zygote is supported on this platform
#[cfg(unix)]
pub fn is_supported() -> bool {
    true
}

#[cfg(not(unix))]
pub fn is_supported() -> bool {
    false
}

/// Get the path to the Zygote log file
pub fn get_log_path() -> PathBuf {
    VeloPaths::zygote_log()
}

/// SEC-005: Generate an ephemeral forensic secret and write it to a .auth file
/// alongside the socket. This file is used for client-side discovery and auth.
/// Returns the secret string.
pub fn write_ephemeral_secret(
    socket_path: &Path,
    provided_secret: Option<String>,
) -> Result<String> {
    let auth_path = VeloPaths::auth_file_for_socket(socket_path);
    let secret = provided_secret.unwrap_or_else(|| uuid::Uuid::now_v7().to_string());

    // Create file with 0600 permissions
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        let mut options = OpenOptions::new();
        options.write(true).create(true).truncate(true).mode(0o600);
        let mut file = options
            .open(&auth_path)
            .map_err(|e| ZygoteError::IOError(format!("Failed to create auth file: {}", e)))?;

        use std::io::Write;
        file.write_all(secret.as_bytes())
            .map_err(|e| ZygoteError::IOError(format!("Failed to write auth secret: {}", e)))?;
    }

    Ok(secret)
}

/// Get Zygote status
pub fn get_status() -> Result<ZygoteResponse> {
    use crate::zygote::core_ipc::{ZygoteCommand, default_socket_path, send_command};

    let socket_path = default_socket_path();
    if !socket_path.exists() {
        return Err(ZygoteError::ConnectionFailed(
            "Socket file not found".to_string(),
        ));
    }

    send_command(
        &socket_path,
        ZygoteCommand::Status {
            request_id: Some(uuid::Uuid::now_v7().to_string()),
        },
        None,
    )
}

/// Find the velo_zygote Python module path
///
/// Search order:
/// 1. VELO_ZYGOTE_PATH environment variable (explicit override)
/// 2. Compiled-in path from CARGO_MANIFEST_DIR (dev builds)
/// 3. Relative to velo executable (installed builds)
/// 4. ~/.local/share/velo/velo_zygote (user install)
/// 5. /usr/local/share/velo/velo_zygote (system install)
/// 6. Current working directory (fallback)
#[allow(clippy::collapsible_if)]
pub fn find_zygote_module(_config: &VeloConfig) -> Result<PathBuf> {
    const ZYGOTE_MAIN: &str = "python/velo_zygote/main.py";

    // 1. Check VELO_ZYGOTE_PATH environment variable (explicit override)
    if let Ok(env_path) = std::env::var("VELO_ZYGOTE_PATH") {
        let path = PathBuf::from(&env_path);
        if path.exists() {
            return Ok(path.canonicalize().unwrap_or(path));
        }
        // If env var is set but path doesn't exist, log warning but continue searching
        eprintln!("⚠️ VELO_ZYGOTE_PATH set but not found: {}", env_path);
    }

    // 2. Search relative to executable (installed and multi-workspace builds)
    // RFC-0013: Prioritizing runtime detection to prevent workspace pollution
    if let Ok(exe_path) = std::env::current_exe() {
        // Search up to 4 levels from executable
        let mut search_dir = exe_path.parent().map(|p| p.to_path_buf());
        for _ in 0..5 {
            if let Some(ref dir) = search_dir {
                let module_path = dir.join(ZYGOTE_MAIN);
                if module_path.exists() {
                    return Ok(module_path.canonicalize().unwrap_or(module_path));
                }
                // Also check share/velo/ subdirectory (FHS-style install)
                let share_path = dir.join("share/velo").join(ZYGOTE_MAIN);
                if share_path.exists() {
                    return Ok(share_path.canonicalize().unwrap_or(share_path));
                }
                search_dir = dir.parent().map(|p| p.to_path_buf());
            }
        }
    }

    // 3. Compiled-in path from CARGO_MANIFEST_DIR (legacy dev/monorepo builds)
    // This is a fallback to support cargo test/run from the source dir
    // RFC-0033: Search up from manifest dir to find workspace root
    let mut manifest_search = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    for _ in 0..4 {
        let path = manifest_search.join(ZYGOTE_MAIN);
        if path.exists() {
            return Ok(path.canonicalize().unwrap_or(path));
        }
        if !manifest_search.pop() {
            break;
        }
    }

    // 4. User install location ~/.local/share/velo/
    if let Ok(home) = std::env::var("HOME") {
        let user_path = PathBuf::from(home)
            .join(".local/share/velo")
            .join(ZYGOTE_MAIN);
        if user_path.exists() {
            return Ok(user_path.canonicalize().unwrap_or(user_path));
        }
    }

    // 5. System install location /usr/local/share/velo/
    let system_path = PathBuf::from("/usr/local/share/velo").join(ZYGOTE_MAIN);
    if system_path.exists() {
        return Ok(system_path.canonicalize().unwrap_or(system_path));
    }

    // 6. Current working directory (fallback)
    let cwd_path = PathBuf::from(ZYGOTE_MAIN);
    if cwd_path.exists() {
        return Ok(cwd_path.canonicalize().unwrap_or(cwd_path));
    }

    Err(ZygoteError::StartFailed(format!(
        "Could not find velo_zygote/main.py. Searched:\n\
         - VELO_ZYGOTE_PATH env var\n\
         - Compiled path: {}\n\
         - Executable relative paths\n\
         - User/System share locations\n\
         - CWD\n\
         Set VELO_ZYGOTE_PATH to override.",
        manifest_search.display()
    )))
}

/// Find the standardized worker launcher script path
pub fn find_worker_launcher(config: &VeloConfig) -> Result<PathBuf> {
    let zygote_main = find_zygote_module(config)?;
    let parent = zygote_main.parent().ok_or_else(|| {
        ZygoteError::StartFailed("Zygote main script has no parent directory".to_string())
    })?;
    let launcher = parent.join("worker_launcher.py");
    if launcher.exists() {
        Ok(launcher)
    } else {
        Err(ZygoteError::StartFailed(format!(
            "worker_launcher.py not found in {}",
            parent.display()
        )))
    }
}

// WorkerHandle is now defined in v_fork.rs and re-exported above

/// Zygote launcher - manages the Zygote process lifecycle
pub struct ZygoteLauncher {
    socket_path: PathBuf,
    zygote_pid: Option<u32>,
    zygote_process: Option<Child>,
    python_path: Option<PathBuf>,
    zygote_stream: Option<core_ipc::ZygoteStream>,
}

impl ZygoteLauncher {
    /// Create a new Zygote launcher with the specified socket path
    pub fn new(socket_path: PathBuf) -> Self {
        Self {
            socket_path,
            zygote_pid: None,
            zygote_process: None,
            python_path: None,
            zygote_stream: None,
        }
    }

    /// Get the PID of the running Zygote process
    pub fn pid(&self) -> Option<u32> {
        self.zygote_pid
    }

    /// Set the Python interpreter path
    pub fn with_python(mut self, python_path: PathBuf) -> Self {
        self.python_path = Some(python_path);
        self
    }

    /// Get the path to the Zygote socket
    pub fn socket_path(&self) -> &Path {
        &self.socket_path
    }

    /// Start the Zygote process with pre-loaded modules
    ///
    /// # Arguments
    /// * `preload` - List of Python modules to pre-import
    /// * `app_name` - Optional app name for affinity verification (WB-004)
    /// * `daemon` - Whether to start as a persistent daemon (disables guardian)
    #[cfg(unix)]
    pub fn start(
        &mut self,
        preload: &[&str],
        app_name: Option<&str>,
        daemon: bool,
        config: &VeloConfig,
    ) -> Result<()> {
        // DEF-61-004: Clean up stale sockets from previous versions before starting
        core_ipc::cleanup_stale_sockets();

        // BUG-001 FIX: Acquire startup lock to prevent race condition
        // Multiple concurrent `velo zygote start` would otherwise all pass is_running()
        // and spawn 100+ instances before socket exists.
        let lock_path = VeloPaths::socket_dir().join("zygote-startup.lock");
        if let Some(parent) = lock_path.parent() {
            // [H-GOV HARDENING] Strictly refuse to 'heal' non-existent parent directories.
            if !parent.exists() {
                return Err(ZygoteError::IOError(format!(
                    "Cannot start Zygote: parent directory for lock does not exist: {:?}",
                    parent
                )));
            }
        }

        let lock_file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(&lock_path)
            .map_err(|e| ZygoteError::IOError(format!("Failed to open startup lock: {}", e)))?;

        #[cfg(unix)]
        {
            use fs2::FileExt;
            lock_file.lock_exclusive().map_err(|e| {
                ZygoteError::IOError(format!("Failed to acquire startup lock: {}", e))
            })?;
        }

        // BUG-001 FIX: Re-check is_running AFTER acquiring lock
        // Another process may have started Zygote while we were waiting for the lock
        if self.is_running() {
            // SEC-005: Ensure auth file also exists (Healing for Stale/Broken State)
            let auth_path = VeloPaths::auth_file_for_socket(&self.socket_path);
            if auth_path.exists() {
                // Release lock (happens on drop) and return success
                return Ok(());
            } else {
                log::warn!(
                    "⚠️ Zygote socket exists but auth file is missing: {}. Triggering restart/healing.",
                    auth_path.display()
                );
                // Proceed to restart logic below...
            }
        }

        // ... existing implementation ...

        // RFC-0018: Auto-sync environment (Zero-Config)
        // Ensure the .venv exists and is up to date before we start.
        if config.auto_sync_enabled {
            let sync = EnvironmentSync::new();
            let project_dir = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
            if let Err(e) = sync.ensure_synced(&project_dir) {
                log::warn!("⚠️ Environment sync failed: {}. Continuing anyway...", e);
            }
        }

        // Detect System Python (RFC-0012 §3.1)
        // V3 mandate: NEVER use user .venv/bin/python for Zygote to maximize COW.
        // HARDENING (Phase 8): Use 'which' to find python3 in PATH first, then fallbacks.
        let python = if let Ok(path) = which::which("python3") {
            // Check if this is a venv python. If so, we should probably try to avoid it,
            // but for now, we trust the system PATH if it's explicitly set.
            // Ideally, we'd check if sys.prefix is /usr or /usr/local.
            path
        } else if cfg!(target_os = "macos") {
            PathBuf::from("/usr/bin/python3")
        } else {
            // On Linux, try common locations
            let p = PathBuf::from("/usr/bin/python3");
            if p.exists() {
                p
            } else {
                PathBuf::from("/usr/local/bin/python3")
            }
        };

        if !python.exists() {
            return Err(ZygoteError::StartFailed(
                "System Python not found. Searched PATH, /usr/bin/python3, /usr/local/bin/python3. Environment Shield requires a system-level interpreter.".to_string()
            ));
        }

        // RFC-0011: Standardized socket path
        let socket_path = self.socket_path.clone();
        log::info!("🚀 V3 Supervisor using socket: {}", socket_path.display());

        // Build command with Airlock (Pillar 1: Env Isolation)
        let mut cmd = Command::new(&python);
        // Pass bootstrap script via -c to avoid temp file TOCTOU
        cmd.arg("-c").arg(BOOTSTRAP_PY);

        // RFC-0012: Surgical Environment Management via Airlock
        let shield = EnvironmentShield::new(config);

        let project_dir = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
        let user_venv_path = project_dir.join(".venv");

        shield
            .enter_app_tier(&mut cmd, &user_venv_path)
            .map_err(ZygoteError::SecurityViolation)?;

        // Inject the socket path for the bootstrap script
        cmd.env("VELO_ZYGOTE_SOCK", &socket_path);

        // =========================================================================
        // Phase 8.0: The Bridge of Truth (Configuration Injection)
        // =========================================================================
        // Explicitly inject the resolved configuration as VELO_* environment variables.
        // This ensures Python shares the exact same "Brain" (configuration) as Rust.
        // These are injected AFTER EnvironmentShield::apply() so they are not scrubbed.

        cmd.env(
            "VELO_GRACEFUL_SHUTDOWN_TIMEOUT",
            config.graceful_shutdown_timeout.to_string(),
        );
        cmd.env(
            "VELO_SOCKET_STARTUP_TIMEOUT",
            config.zygote_socket_timeout.to_string(),
        );
        cmd.env("VELO_MAX_BUNDLE_SIZE", config.max_bundle_size.to_string());
        cmd.env(
            "VELO_SLOW_THRESHOLD_MS",
            config.slow_threshold_ms.to_string(),
        );
        cmd.env(
            "VELO_SECURITY_HPC_THREADS",
            config.security_hpc_threads.to_string(),
        );
        cmd.env(
            "VELO_ZYGOTE_MAX_POOL_SIZE",
            config.zygote_max_pool_size.to_string(),
        );

        // Pass preload modules for speculative pre-loading
        if !config.preload.is_empty() {
            cmd.env("VELO_PRELOAD", config.preload.join(","));
        }

        // Inject current executable path for native preload helper
        if let Ok(exe_path) = std::env::current_exe() {
            cmd.env("VELO_RUNTIME_EXE_PATH", exe_path);
        }

        // 3.2 RFC-0035: Native Preload for Zygote (Moved to VELO_RUNTIME_PRELOAD_LOCK)
        let lock_path = project_dir.join("preload.lock");
        if lock_path.exists()
            && let Ok(lock_json) = std::fs::read_to_string(&lock_path)
        {
            cmd.env("VELO_RUNTIME_PRELOAD_LOCK", lock_json);
        }

        // --- Bridge of Truth: Structured Environment Propagation (SPEC-0005) ---
        Self::propagate_velo_context(&mut cmd);

        // Identification env for bootstrap
        cmd.env("VELO_IS_ZYGOTE", "1");

        // RFC-0012: Ensure our own python/ source root is trusted and searchable
        // This is critical after the reorganization to python/velo_zygote/
        if let Ok(cwd) = std::env::current_dir() {
            let python_root = cwd.join("python");
            if let Ok(existing) = std::env::var("PYTHONPATH") {
                let mut paths = vec![python_root.to_string_lossy().to_string()];
                paths.push(existing);
                cmd.env("PYTHONPATH", paths.join(":"));
            } else {
                cmd.env("PYTHONPATH", python_root);
            }
        }

        // Pass app name if present
        if let Some(app) = app_name {
            cmd.env("VELO_APP_NAME", app);
        }

        // SEC-005: Pass forensic secret for external auth (Removed redundant arg)

        #[cfg(target_os = "linux")]
        let strict_optimizations = config.strict_optimizations;
        #[cfg(target_os = "linux")]
        let network_isolation = crate::common::constants::SANDBOX_NETWORK_ISOLATION;
        #[cfg(target_os = "linux")]
        let priv_block = crate::common::constants::SANDBOX_PRIVILEGE_ESCALATION_BLOCK;

        // Detach from parent process group so Zygote survives CLI exit
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;

            let test_mode = std::env::var("VELO_TEST_MODE").unwrap_or_default() == "1";
            unsafe {
                cmd.pre_exec(move || {
                    // 1. Create new session (setsid) to detach from parent
                    // Skip in test mode to keep process group cleanup effective.
                    if !test_mode || daemon {
                        libc::setsid();
                    }

                    // 2. Linux-specific Hardening (Pillar 3+)
                    #[cfg(target_os = "linux")]
                    {
                        // RFC-0011 Linux-Shield: Network Isolation
                        // Use unshare to create a private network namespace (effectively disabling global network access)
                        // Note: This requires CLONE_NEWNET.
                        // Only enabled when strict_optimizations is TRUE (Prod mode) or via SSOT.
                        if (strict_optimizations || network_isolation)
                            && libc::unshare(libc::CLONE_NEWNET) != 0
                        {
                            // We continue even if it fails, as some old kernels might not support it
                            // but ideally, we should log a warning if we had a logger here.
                        }

                        // RFC-0011 Linux-Shield: Prevent privilege escalation
                        // PR_SET_NO_NEW_PRIVS ensures that the process and its children cannot gain new privileges (e.g., via setuid)
                        if (strict_optimizations || priv_block)
                            && libc::prctl(libc::PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0
                        {
                            // Same here, fallback gracefully
                        }

                        // RFC-0012 TITANIUM Hardening: No Orphans Rule
                        // Only set PR_SET_PDEATHSIG if we are NOT in daemon mode.
                        // A daemonized Zygote is INTENDED to outlive its parent CLI.
                        if !daemon
                            && libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGKILL, 0, 0, 0) != 0
                        {
                            // Fallback gracefully if not supported
                        }
                    }

                    Ok(())
                });
            }
        }

        // Setup logging - Redirect stdout/stderr to log file for daemon mode
        if daemon {
            let log_path = get_log_path();
            if let Some(parent) = log_path.parent() {
                let _ = fs::create_dir_all(parent);
            }

            let log_file = OpenOptions::new()
                .create(true)
                .append(true)
                .open(&log_path)
                .map_err(|e| {
                    ZygoteError::StartFailed(format!(
                        "Failed to open log file {}: {}",
                        log_path.display(),
                        e
                    ))
                })?;

            cmd.stdout(Stdio::from(log_file.try_clone().map_err(|e| {
                ZygoteError::StartFailed(format!("Failed to clone log file handle: {}", e))
            })?));
            cmd.stderr(Stdio::from(log_file));
        }

        // Create the listener BEFORE spawning the Zygote (RFC-0012)
        let listener = core_ipc::create_listener(&self.socket_path)?;

        // Spawn the Zygote process
        let child = cmd
            .spawn()
            .map_err(|e| ZygoteError::StartFailed(format!("Failed to spawn Zygote: {}", e)))?;

        let pid = child.id();
        self.zygote_process = Some(child);
        self.zygote_pid = Some(pid);

        // Wait for Zygote to connect back (with timeout)
        // Accept the connection from the shim
        // We use a non-blocking accept or a timeout on the listener
        let (stream, _) = listener.accept().map_err(|e| {
            ZygoteError::StartFailed(format!("Failed to accept Zygote connection: {}", e))
        })?;

        // WB-002: Reliability - Set handshake timeout
        stream
            .set_read_timeout(Some(std::time::Duration::from_secs(5)))
            .map_err(|e| ZygoteError::SocketError(e.to_string()))?;

        // 1. Receive mandatory "Ready" greeting
        let mut zygote_stream = core_ipc::ZygoteStream::from_stream(stream);
        let (ready, fd): (core_ipc::ZygoteResponse, _) =
            core_ipc::read_message(&mut zygote_stream.stream)?;
        if let Some(fd) = fd {
            let _ = nix::unistd::close(fd);
        }

        if !matches!(ready, core_ipc::ZygoteResponse::Ready) {
            return Err(ZygoteError::ProtocolError(format!(
                "Connection greeting failed - expected Ready, got {:?}",
                ready
            )));
        }

        log::info!("Zygote Shim detected. Performing handshake...");

        // 2. Perform Handshake
        log::debug!("Performing protocol handshake...");
        let handshake_cmd = core_ipc::ZygoteCommand::Handshake {
            version: core_ipc::PROTOCOL_VERSION,
            capabilities: vec!["v3-shim".to_string()],
            request_id: Some(uuid::Uuid::now_v7().to_string()),
        };
        let response = zygote_stream.send_command(&handshake_cmd, None)?;

        if let core_ipc::ZygoteResponse::Handshake {
            version,
            capabilities,
        } = response
        {
            log::info!(
                "Handshake successful (v{}, caps: {:?})",
                version,
                capabilities
            );
            self.zygote_stream = Some(zygote_stream);

            // RFC-0028 P2: Initialize the warm pool
            if let Err(e) = self.sync_pool_size(config) {
                log::error!("[ZygoteLauncher] Initial pool sync failed: {}", e);
            }
        } else {
            return Err(ZygoteError::ProtocolError("Handshake failed".to_string()));
        }

        // 3. Deep Probe: Status check
        log::debug!("Sending deep liveness probe (Status)...");
        let base_boot_timeout = 30.0;
        let boot_timeout = std::time::Duration::from_secs_f64(
            base_boot_timeout * config.zygote_socket_timeout as f64 / 30.0,
        );
        let boot_start = std::time::Instant::now();
        let final_pid: u32;

        loop {
            let status_cmd = core_ipc::ZygoteCommand::Status {
                request_id: Some(uuid::Uuid::now_v7().to_string()),
            };
            // Use the stored zygote_stream for subsequent commands
            let response = self
                .zygote_stream
                .as_mut()
                .unwrap()
                .send_command(&status_cmd, None)?;

            if let core_ipc::ZygoteResponse::Status {
                pid,
                state,
                preload_done,
                ..
            } = response
            {
                if self.zygote_pid.is_some() && self.zygote_pid != Some(pid) {
                    log::warn!(
                        "Deep probe PID mismatch: got {}, expected {} (Possible Shadow Trap, but continuing)",
                        pid,
                        self.zygote_pid.unwrap()
                    );
                }
                log::info!(
                    "Zygote deep probe: PID={}, State={}, PreloadDone={}",
                    pid,
                    state,
                    preload_done
                );

                if state == "ERROR" {
                    return Err(ZygoteError::ProtocolError(
                        "Zygote is in ERROR state. Check Zygote log for details.".to_string(),
                    ));
                }

                // If we are pre-warming an app, we MUST wait for preload_done
                // otherwise the supervisor might start spawning workers before the app is ready.
                if state == "READY" && (app_name.is_none() || preload_done) {
                    log::info!("Zygote fully initialized.");
                    final_pid = pid;
                    break;
                }
            } else {
                return Err(ZygoteError::StartFailed(
                    "Deep probe failed: invalid response".to_string(),
                ));
            }

            if boot_start.elapsed() > boot_timeout {
                return Err(ZygoteError::StartFailed(format!(
                    "Timeout waiting for Zygote initialization after 30s. Progress: state={}, preload_done={}",
                    // We can't easily get the last state here without saving it, but it's fine for now
                    "UNKNOWN",
                    "UNKNOWN"
                )));
            }
            std::thread::sleep(std::time::Duration::from_millis(100));
        }

        // Phase 15: Initialize the Rust Guardian with Restart Capabilities (P1)
        // Skip Guardian for daemon mode (vtest use case) - the caller manages lifecycle
        if !daemon {
            let params = guardian::ZygoteStartParams {
                preload: preload.iter().map(|s| s.to_string()).collect(),
                app_name: app_name.map(|s| s.to_string()),
                python_path: python.clone(),
                config: config.clone(),
            };

            let guardian =
                guardian::ZygoteGuardian::new(self.socket_path.clone(), final_pid, Some(params));
            if let Err(e) = guardian.start() {
                log::warn!("[Guardian] Failed to start background supervisor: {}", e);
            } else {
                log::info!("🛡️ Rust Guardian engaged for Zygote PID {}", final_pid);
            }
        }

        Ok(())
    }

    #[cfg(not(unix))]
    pub fn start(
        &mut self,
        _preload: &[&str],
        _app_name: Option<&str>,
        _daemon: bool,
    ) -> Result<()> {
        Err(ZygoteError::NotSupported)
    }

    /// Stop the Zygote process gracefully
    /// Only sends Shutdown if this launcher owns the Zygote process
    pub fn stop(&mut self) -> Result<()> {
        // Only stop if we OWN the Zygote process (not just connecting to existing one)
        // In test mode, allow shutdown even without ownership to prevent orphaned daemons.
        let test_mode = std::env::var("VELO_TEST_MODE").unwrap_or_default() == "1";
        if self.zygote_process.is_none() && !test_mode {
            return Ok(());
        }

        // Try to send shutdown command
        if let Some(ref mut stream) = self.zygote_stream {
            let _ = stream.send_command(&core_ipc::ZygoteCommand::Shutdown, None);
        } else if self.socket_path.exists() {
            let _ =
                core_ipc::send_command(&self.socket_path, core_ipc::ZygoteCommand::Shutdown, None);
        }

        #[cfg(unix)]
        if test_mode
            && let Ok(output) = std::process::Command::new("/bin/ps")
                .args(["-ax", "-o", "pid=,command="])
                .output()
            && let Ok(text) = String::from_utf8(output.stdout)
        {
            let needle = self.socket_path.to_string_lossy();
            for line in text.lines() {
                if !line.contains("python/velo_zygote/main.py") || !line.contains(needle.as_ref()) {
                    continue;
                }
                let mut parts = line.split_whitespace();
                let Some(pid_str) = parts.next() else {
                    continue;
                };
                if let Ok(pid) = pid_str.parse::<i32>() {
                    unsafe {
                        let _ = libc::kill(pid, libc::SIGKILL);
                    }
                }
            }
        }

        // SEC-005: Clean up ephemeral auth file
        let auth_path = VeloPaths::auth_file_for_socket(&self.socket_path);
        if auth_path.exists() {
            let _ = std::fs::remove_file(auth_path);
        }

        // Wait for process to exit or kill it
        if let Some(mut child) = self.zygote_process.take() {
            // Give it a moment to shut down gracefully
            // RFC-0012 C.6: Increased from 100ms to 2000ms to allow Zygote to kill its workers
            std::thread::sleep(Duration::from_millis(2000));

            // Check if it's still running
            match child.try_wait() {
                Ok(Some(_)) => {
                    // Already exited
                }
                Ok(None) => {
                    // RFC-0012 C.6: Robust Eradication - Kill the entire process group.
                    // Since Zygote uses setsid(), its PGID == PID.
                    #[cfg(unix)]
                    unsafe {
                        let pgid = child.id() as i32;
                        // Try to kill process group first
                        if libc::kill(-pgid, libc::SIGKILL) != 0 {
                            // Fallback to killing just the child
                            let _ = child.kill();
                        }
                    }
                    #[cfg(not(unix))]
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
        log::debug!(
            "[ZygoteLauncher::stop] Cleaning up socket: {:?}",
            self.socket_path
        );
        core_ipc::cleanup_socket(&self.socket_path);
        self.zygote_pid = None;

        Ok(())
    }

    /// Check if the Zygote process is running.
    /// Either we own the process (zygote_pid set) or socket exists (external Zygote).
    pub fn is_running(&mut self) -> bool {
        self.is_alive()
    }

    /// Robust liveness check for the Zygote process (First Principles).
    ///
    /// This check prioritizes process membership (Wait Status) over network probes.
    /// Probing the socket with connect() and dropping it immediately can cause
    /// BrokenPipeError on the Zygote side if it's in the middle of a handshake.
    pub fn is_alive(&mut self) -> bool {
        if let Some(ref mut child) = self.zygote_process {
            match child.try_wait() {
                Ok(None) => {
                    // Process is still running according to the OS.
                    // Trust the OS handle - deep probes are expensive.
                    true
                }
                _ => {
                    // Process died or error
                    self.zygote_pid = None;
                    self.zygote_process = None;
                    false
                }
            }
        } else {
            // If we don't own the process, a probe is the only way.
            core_ipc::is_socket_responsive(&self.socket_path)
        }
    }

    /// Get status information about the Zygote
    pub fn status(&self) -> String {
        match self.zygote_pid {
            Some(pid) => format!("Running (PID: {})", pid),
            None => "Not running".to_string(),
        }
    }

    /// Sync the target pool size to the Zygote shim (RFC-0028 P2)
    pub fn sync_pool_size(&mut self, config: &VeloConfig) -> Result<()> {
        if let Some(ref mut stream) = self.zygote_stream {
            log::debug!(
                "[ZygoteLauncher] Syncing pool size: {}",
                config.zygote_pool_size
            );
            let cmd = core_ipc::ZygoteCommand::ReplenishPool {
                target_count: config.zygote_pool_size,
                request_id: Some(uuid::Uuid::now_v7().to_string()),
            };
            match stream.send_command(&cmd, None) {
                Ok(core_ipc::ZygoteResponse::Ack) => Ok(()),
                Ok(other) => Err(ZygoteError::ProtocolError(format!(
                    "Unexpected response to ReplenishPool: {:?}",
                    other
                ))),
                Err(e) => Err(e),
            }
        } else {
            Ok(())
        }
    }

    /// Fork a new worker from the Zygote
    /// Delegates to v_fork::spawn_worker (RFC-0028 §10.3.5)
    #[allow(clippy::too_many_arguments)]
    pub fn spawn_worker(
        &mut self,
        script: &Path,
        module: Option<String>,
        args: &[&str],
        async_mode: bool,
        fast_mode: bool,
        bundle_path: Option<PathBuf>,
        project_root: Option<PathBuf>,
        max_bundle_size: Option<u64>,
        shm_file: Option<&std::fs::File>,
        env_overrides: Option<std::collections::HashMap<String, String>>,
        config: &VeloConfig,
    ) -> Result<WorkerHandle> {
        log::info!(
            "[ZygoteLauncher] spawn_worker: zygote_stream is Some: {}",
            self.zygote_stream.is_some()
        );
        if let Some(ref mut zygote_stream) = self.zygote_stream {
            // After spawning, the shim has already triggered a background replenishment if using pool.
            v_fork::spawn_worker_via_stream(
                zygote_stream,
                script,
                module,
                args,
                async_mode,
                fast_mode,
                bundle_path,
                project_root,
                max_bundle_size,
                shm_file,
                env_overrides,
                config,
            )
        } else {
            v_fork::spawn_worker(
                &self.socket_path,
                script,
                module,
                args,
                async_mode,
                fast_mode,
                bundle_path,
                project_root,
                max_bundle_size,
                shm_file,
                env_overrides,
                config,
            )
        }
    }

    /// Propagate Velo context from Supervisor to Zygote/Worker (SPEC-0005)
    ///
    /// Following the "Prefix-Directed Intent" (SPEC-0006), this automatically
    /// inherits all VELO_ prefixed variables except VELO_SYS_ secrets.
    fn propagate_velo_context(cmd: &mut std::process::Command) {
        // 1. Explicitly inherit platform context for CI resilience
        for key in &["CI", "GITHUB_ACTIONS"] {
            if let Ok(val) = std::env::var(key) {
                cmd.env(key, val);
            }
        }

        // 2. Resolve default VELO_ENV if not set (Ritual 21.4)
        if std::env::var("VELO_ENV").is_err() {
            let is_ci = std::env::var("GITHUB_ACTIONS")
                .map(|v| v == "true")
                .unwrap_or(false);
            let mode = if is_ci { "ci" } else { "dev" };
            cmd.env("VELO_ENV", mode);
        }

        // 3. Structured inheritance of Sovereign variables
        for (key, val) in std::env::vars() {
            if key.starts_with("VELO_") {
                // Tiered Security: Scrub System/Secret variables (SPEC-0005)
                if key.starts_with("VELO_SYS_") {
                    continue;
                }
                cmd.env(key, val);
            }
        }
    }
}

impl Drop for ZygoteLauncher {
    fn drop(&mut self) {
        // Ensure cleanup on drop
        let _ = self.stop();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_get_log_path() {
        let path = get_log_path();
        assert!(path.to_string_lossy().contains("zygote.log"));
    }

    #[test]
    fn test_environment_shield_basic() {
        let shield = EnvironmentShield::new(&crate::config::VeloConfig::default());
        // /usr/bin should be trusted
        assert!(shield.validate_path_variable("/usr/bin").is_ok());

        // RFC §3.5: /tmp should be scrubbed out (filtered) from PATH
        let res = shield.validate_path_variable("/tmp");
        assert!(res.is_ok());
        assert!(res.unwrap().is_empty());
    }
}
