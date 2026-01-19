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
pub mod core_ipc;
pub mod error;
pub mod guardian;
pub mod peer_check;
pub mod v_fork;

// Re-export v_fork types for backward compatibility (RFC-0028 §10.3.5)
pub use v_fork::{WorkerHandle, spawn_worker};

extern crate log;

use crate::common::paths::VeloPaths;
use crate::config::VeloConfig;
use crate::lifecycle::{EnvironmentShield, apply_standard_hygiene};
use core_ipc::{ZygoteResponse, is_socket_alive};
use error::{Result, ZygoteError};
use std::fs::{self, OpenOptions};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::Duration;

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

fn get_socket_timeout_secs() -> u64 {
    VeloConfig::from_env_only().zygote_socket_timeout
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
    use core_ipc::{ZygoteCommand, default_socket_path, send_command};

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
    const ZYGOTE_MAIN: &str = "velo_zygote/main.py";

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
    let manifest_path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(ZYGOTE_MAIN);
    if manifest_path.exists() {
        return Ok(manifest_path.canonicalize().unwrap_or(manifest_path));
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
        manifest_path.display()
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

    /// Get the PID of the running Zygote process
    pub fn pid(&self) -> Option<u32> {
        self.zygote_pid
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

        if self.is_running() {
            return Ok(());
        }

        // ... existing implementation ...

        // Find Python interpreter using standardized detection (respects VELO_PYTHON)
        let project_dir = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
        let python = self.python_path.clone().unwrap_or_else(|| {
            crate::python::detect_python(&project_dir).unwrap_or_else(|_| PathBuf::from("python3"))
        });

        // RFC-0011: Standardized socket path
        let socket_path = crate::zygote::core_ipc::default_socket_path();
        log::info!("🚀 Zygote using socket: {}", socket_path.display());

        // Find zygote module
        let zygote_module = find_zygote_module(config)?;

        // Build command with EnvShield (Pillar 1: Env Isolation)
        // Use 'env' to wrapper execution (Workaround for macOS symlink/Command::new issue)
        let mut cmd = Command::new("env");
        cmd.arg(&python);

        // RFC-0012: Surgical Environment Management (§3.1 & §3.5)
        let shield = EnvironmentShield::new(config);

        shield
            .apply_with_python(&mut cmd, &python)
            .map_err(ZygoteError::SecurityViolation)?;

        // Pass GITHUB_ACTIONS to allow /home paths in CI
        if let Ok(val) = std::env::var("GITHUB_ACTIONS") {
            cmd.env("GITHUB_ACTIONS", val);
        }

        // RFC-0012 §3.6: FD & Signal Hygiene
        apply_standard_hygiene(&mut cmd);

        // Unified Python Environment Resolution (SSOT)
        // Defect Fix: Ensure Zygote environment is derived from the Python binary
        // (via PythonEnv::detect) rather than relying on unstable manual forwarding.
        // This handles PYTHONHOME/VIRTUAL_ENV reconstruction automatically.
        // [CI-FORCE] Verifying regression fix in production pipeline.
        match crate::common::python_env::PythonEnv::detect(&python) {
            Ok(py_env) => {
                py_env.apply_to_command(&mut cmd);
                log::info!(
                    "[SSOT] Zygote Python env: base={:?}, version={}",
                    py_env.base_prefix,
                    py_env.version
                );
            }
            Err(e) => {
                log::warn!(
                    "[SSOT] Failed to detect Python environment for Zygote: {}",
                    e
                );
                // Fallback: Try to inject VIRTUAL_ENV if present in parent
                if let Ok(venv) = std::env::var("VIRTUAL_ENV") {
                    cmd.env("VIRTUAL_ENV", venv);
                }
            }
        }

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

        // --- Bridge of Truth: Inject Environment Context ---
        let github_actions = std::env::var("GITHUB_ACTIONS")
            .map(|v| v.to_lowercase())
            .unwrap_or_default();
        let velo_env_current = std::env::var("VELO_ENV").ok();

        let env_mode = match (velo_env_current, github_actions.as_str()) {
            (Some(env), _) => env,
            (None, "true") => "ci".to_string(),
            (None, _) => "dev".to_string(),
        };
        cmd.env("VELO_ENV", &env_mode);

        if let Ok(val) = std::env::var("VELO_SOCKET_DIR") {
            cmd.env("VELO_SOCKET_DIR", val);
        }
        if let Ok(val) = std::env::var("VELO_ZYGOTE_LOG") {
            cmd.env("VELO_ZYGOTE_LOG", val);
        }
        if let Ok(val) = std::env::var("VELO_ZYGOTE_SOCKET") {
            cmd.env("VELO_ZYGOTE_SOCKET", val);
        }

        // Identify this as the Zygote process for bootstrap logic (Trap 178.4)
        cmd.env("VELO_IS_ZYGOTE", "1");

        // Also inject boolean flags if necessary (currently none in VeloConfig that aren't implicit)
        // =========================================================================

        // RFC-0011 D.1: Handle abstract socket path for CLI (convert \0 to @)
        let socket_arg = {
            #[cfg(target_os = "linux")]
            {
                use std::os::unix::ffi::OsStrExt;
                let bytes = self.socket_path.as_os_str().as_bytes();
                if !bytes.is_empty() && bytes[0] == 0 {
                    let mut s = String::from("@");
                    s.push_str(&String::from_utf8_lossy(&bytes[1..]));
                    s
                } else {
                    self.socket_path.to_string_lossy().to_string()
                }
            }
            #[cfg(not(target_os = "linux"))]
            self.socket_path.to_string_lossy().to_string()
        };

        // Pillar 3: Sandbox Isolation (SandboxShield)
        // On macOS, we use sandbox-exec (Seatbelt) to restrict the Zygote process.
        #[allow(unexpected_cfgs)]
        #[cfg(not(feature = "sandbox_disabled"))]
        #[cfg(target_os = "macos")]
        if std::env::var("VELO_TEST_MODE").unwrap_or_default() != "1" {
            let socket_dir = self
                .socket_path
                .parent()
                .unwrap_or_else(|| Path::new("/tmp"));
            let log_path = get_log_path();
            let log_dir = log_path.parent().unwrap_or_else(|| Path::new("/tmp"));

            let profile = format!(
                r#"(version 1)
(allow default)
(allow file-read*)
(allow file-write*
    (subpath "/tmp")
    (subpath "/private/tmp")
    (subpath "/var/folders")
    (subpath "{}")
    (subpath "{}")
    (subpath "{}")
)
"#,
                std::env::current_dir().unwrap_or_default().display(),
                socket_dir.display(),
                log_dir.display()
            );

            // Enable Sandbox
            let mut sandbox_cmd = Command::new("sandbox-exec");
            sandbox_cmd.arg("-p").arg(profile);

            // Transfer shielded environment from 'cmd' to 'sandbox_cmd'
            // RFC-0014: Ensure we inherit process env so critical fixes (like OBJC_DISABLE_INITIALIZE_FORK_SAFETY) persist.
            for (k, v) in std::env::vars() {
                sandbox_cmd.env(k, v);
            }
            for (k, v) in cmd.get_envs() {
                if let Some(val) = v {
                    sandbox_cmd.env(k, val);
                }
            }
            // RFC-0012: Resilience - Use formal whitelist from SSOT (Configuration De-Hellification)
            for var in &config.security_env_whitelist {
                if let Ok(val) = std::env::var(var) {
                    sandbox_cmd.env(var, val);
                }
            }
            // HPC/OMP Thread pooling isolation
            if let Ok(val) = std::env::var("GITHUB_ACTIONS") {
                sandbox_cmd.env("GITHUB_ACTIONS", val);
            }

            sandbox_cmd.env("OMP_NUM_THREADS", "1");
            sandbox_cmd.env("MKL_NUM_THREADS", "1");
            sandbox_cmd.env("OPENBLAS_NUM_THREADS", "1");
            sandbox_cmd.env("VECLIB_MAXIMUM_THREADS", "1");
            sandbox_cmd.env("NUMEXPR_NUM_THREADS", "1");

            sandbox_cmd.env("PYTHONDONTWRITEBYTECODE", "1");
            sandbox_cmd.env("PYTHONIOENCODING", "utf-8");
            sandbox_cmd.env("PYTHONUTF8", "1");

            // Execute python directly
            sandbox_cmd.arg(&python);

            cmd = sandbox_cmd;
        }
        // Dangling code removed

        cmd.arg(&zygote_module).arg("--socket").arg(socket_arg);

        // SEC-005: Generate and propagate forensic auth secret
        // Use provided secret from config if available (respecting VELO_ZYGOTE_AUTH)
        if let Ok(secret) =
            write_ephemeral_secret(&self.socket_path, config.forensic_secret.clone())
        {
            cmd.arg("--authorized-secret").arg(secret);
        }

        if daemon {
            cmd.arg("--no-guardian");
        }

        if !preload.is_empty() {
            cmd.arg("--preload");
            for module in preload {
                cmd.arg(module);
            }
        }

        // RFC-0011 WB-004: Pass app name for affinity verification
        if let Some(app) = app_name {
            cmd.arg("--app").arg(app);
        }

        // SEC-005: Pass forensic secret for external auth (Removed redundant arg)

        #[cfg(target_os = "linux")]
        let strict_optimizations = config.strict_optimizations;

        // Detach from parent process group so Zygote survives CLI exit
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;

            unsafe {
                cmd.pre_exec(move || {
                    // 1. Create new session (setsid) to detach from parent
                    libc::setsid();

                    // 2. Linux-specific Hardening (Pillar 3+)
                    #[cfg(target_os = "linux")]
                    {
                        // RFC-0011 Linux-Shield: Network Isolation
                        // Use unshare to create a private network namespace (effectively disabling global network access)
                        // Note: This requires CLONE_NEWNET.
                        // Only enabled when strict_optimizations is TRUE (Prod mode).
                        if strict_optimizations && libc::unshare(libc::CLONE_NEWNET) != 0 {
                            // We continue even if it fails, as some old kernels might not support it
                            // but ideally, we should log a warning if we had a logger here.
                        }

                        // RFC-0011 Linux-Shield: Prevent privilege escalation
                        // PR_SET_NO_NEW_PRIVS ensures that the process and its children cannot gain new privileges (e.g., via setuid)
                        if libc::prctl(libc::PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0 {
                            // Same here, fallback gracefully
                        }

                        // RFC-0012 TITANIUM Hardening: No Orphans Rule
                        // PR_SET_PDEATHSIG ensures that the Zygote is killed if its parent supervisor dies.
                        // This prevents leaks and "Shadow Traps" in production.
                        if libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGKILL, 0, 0, 0) != 0 {
                            // Fallback gracefully if not supported
                        }
                    }

                    Ok(())
                });
            }
        }

        // Setup logging - Redirect stdout/stderr to log file for daemon mode
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

        // Spawn the Zygote process
        let child = cmd
            .spawn()
            .map_err(|e| ZygoteError::StartFailed(format!("Failed to spawn Zygote: {}", e)))?;

        let pid = child.id();
        self.zygote_process = Some(child);
        self.zygote_pid = Some(pid);

        // Wait for socket to be created (with timeout)
        let timeout_secs = get_socket_timeout_secs();
        let timeout = Duration::from_secs(timeout_secs);
        let start = std::time::Instant::now();

        // RFC-0011 D.1: Use is_socket_alive instead of exists() to support abstract sockets
        while !is_socket_alive(&self.socket_path) {
            // Check if process is still running (DEF-61-005)
            if let Some(ref mut child) = self.zygote_process {
                match child.try_wait() {
                    Ok(Some(status)) => {
                        return Err(ZygoteError::StartFailed(format!(
                            "Zygote process exited prematurely with status: {}. Check log at: {}",
                            status,
                            get_log_path().display()
                        )));
                    }
                    Ok(None) => {
                        // Still running, wait more
                    }
                    Err(e) => {
                        return Err(ZygoteError::StartFailed(format!(
                            "Error checking Zygote status: {}",
                            e
                        )));
                    }
                }
            }

            if start.elapsed() > timeout {
                let _ = self.stop();
                return Err(ZygoteError::StartFailed(format!(
                    "Timeout waiting for Zygote socket after {}s. Check log at: {}",
                    timeout_secs,
                    get_log_path().display()
                )));
            }
            std::thread::sleep(Duration::from_millis(5));
        }

        // Layer 3: Deep Liveness Probe & Handshake (RFC-0011 architectural requirement)
        log::info!("Zygote socket detected. Performing deep probe...");

        // 1. Connect and verify Ready greeting (handled by ZygoteStream::connect)
        let mut zygote_stream = core_ipc::ZygoteStream::connect(&self.socket_path)?;

        // 2. Perform Handshake
        log::debug!("Performing protocol handshake...");
        let handshake_cmd = core_ipc::ZygoteCommand::Handshake {
            version: core_ipc::PROTOCOL_VERSION,
            capabilities: vec!["map-protocol".to_string(), "async-reaper".to_string()],
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
        } else {
            return Err(ZygoteError::ProtocolError("Handshake failed".to_string()));
        }

        // 3. Deep Probe: Status check
        log::debug!("Sending deep liveness probe (Status)...");
        let status_cmd = core_ipc::ZygoteCommand::Status {
            request_id: Some(uuid::Uuid::now_v7().to_string()),
        };
        let response = zygote_stream.send_command(&status_cmd, None)?;

        if let core_ipc::ZygoteResponse::Status { pid, .. } = response {
            if self.zygote_pid.is_some() && self.zygote_pid != Some(pid) {
                log::warn!(
                    "Deep probe PID mismatch: got {}, expected {} (Possible Shadow Trap, but continuing)",
                    pid,
                    self.zygote_pid.unwrap()
                );
            }
            log::info!("Zygote deep probe successful (PID: {}).", pid);

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
                    guardian::ZygoteGuardian::new(self.socket_path.clone(), pid, Some(params));
                if let Err(e) = guardian.start() {
                    log::warn!("[Guardian] Failed to start background supervisor: {}", e);
                } else {
                    log::info!("🛡️ Rust Guardian engaged for Zygote PID {}", pid);
                }
            }
        } else {
            return Err(ZygoteError::StartFailed(
                "Deep probe failed: invalid response".to_string(),
            ));
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
        if self.zygote_process.is_none() {
            return Ok(());
        }

        // Try to send shutdown command
        if self.socket_path.exists() {
            let _ =
                core_ipc::send_command(&self.socket_path, core_ipc::ZygoteCommand::Shutdown, None);
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

    /// Fork a new worker from the Zygote
    /// Delegates to v_fork::spawn_worker (RFC-0028 §10.3.5)
    #[allow(clippy::too_many_arguments)]
    pub fn spawn_worker(
        &mut self,
        script: &Path,
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
        v_fork::spawn_worker(
            &self.socket_path,
            script,
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
