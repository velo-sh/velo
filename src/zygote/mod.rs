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

extern crate log;

use crate::common::paths::VeloPaths;
use crate::config::VeloConfig;
use crate::lifecycle::{EnvironmentShield, apply_standard_hygiene};
use error::{Result, ZygoteError};
use ipc::{ZygoteResponse, is_socket_alive};
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

fn get_worker_timeout_secs() -> u64 {
    // Both worker and socket timeouts are now centralized
    VeloConfig::from_env_only().zygote_socket_timeout
}

fn get_socket_timeout_secs() -> u64 {
    VeloConfig::from_env_only().zygote_socket_timeout
}

/// Get the path to the Zygote log file
pub fn get_log_path() -> PathBuf {
    VeloPaths::zygote_log()
}

/// Get Zygote status
pub fn get_status() -> Result<ZygoteResponse> {
    use ipc::{ZygoteCommand, default_socket_path, send_command};

    let socket_path = default_socket_path();
    if !socket_path.exists() {
        return Err(ZygoteError::ConnectionFailed(
            "Socket file not found".to_string(),
        ));
    }

    send_command(&socket_path, ZygoteCommand::Status, None)
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
fn find_zygote_module() -> Result<PathBuf> {
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
pub fn find_worker_launcher() -> Result<PathBuf> {
    let zygote_main = find_zygote_module()?;
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

/// Handle to a spawned worker process
pub struct WorkerHandle {
    pid: u32,
    stdout_path: Option<PathBuf>,
    stderr_path: Option<PathBuf>,
    exit_code_path: Option<PathBuf>,
}

impl WorkerHandle {
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

                // Fast polling for first 100ms, then slower
                if start.elapsed().as_millis() < 100 {
                    std::thread::sleep(std::time::Duration::from_millis(1));
                } else {
                    std::thread::sleep(std::time::Duration::from_millis(10));
                }
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
        ipc::cleanup_stale_sockets();

        if self.is_running() {
            return Ok(());
        }

        // Find Python interpreter
        let python = self.python_path.clone().unwrap_or_else(|| {
            // Default to python3
            PathBuf::from("python3")
        });

        // RFC-0011: Standardized socket path
        let socket_path = crate::zygote::ipc::default_socket_path();
        log::info!("🚀 Zygote using socket: {}", socket_path.display());

        // Find zygote module
        let zygote_module = find_zygote_module()?;

        // Build command with EnvShield (Pillar 1: Env Isolation)
        // Use 'env' to wrapper execution (Workaround for macOS symlink/Command::new issue)
        let mut cmd = Command::new("env");
        cmd.arg(&python);
        // cmd.env_clear();

        // RFC-0012: Surgical Environment Management (§3.1 & §3.5)
        let shield = EnvironmentShield::new(config);
        shield
            .apply(&mut cmd)
            .map_err(ZygoteError::SecurityViolation)?;

        // Pass GITHUB_ACTIONS to allow /home paths in CI
        if let Ok(val) = std::env::var("GITHUB_ACTIONS") {
            cmd.env("GITHUB_ACTIONS", val);
        }

        // RFC-0012 §3.6: FD & Signal Hygiene
        apply_standard_hygiene(&mut cmd);

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
        {
            let profile = format!(
                r#"(version 1)
(allow default)
(allow file-read*)
(deny file-write*
    (subpath "/Users")
    (subpath "/Library")
    (subpath "/etc")
)
(allow file-write*
    (subpath "/tmp")
    (subpath "/private/tmp")
    (subpath "/var/folders")
    (subpath "{}")
    (subpath "{}")
)
"#,
                std::env::current_dir().unwrap_or_default().display(),
                ipc::get_socket_dir().display()
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
            let config = VeloConfig::default();
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

        // Detach from parent process group so Zygote survives CLI exit
        #[cfg(unix)]
        unsafe {
            use std::os::unix::process::CommandExt;
            cmd.pre_exec(|| {
                // 1. Create new session (setsid) to detach from parent
                libc::setsid();

                // 2. Linux-specific Hardening (Pillar 3+)
                #[cfg(target_os = "linux")]
                {
                    // RFC-0011 Linux-Shield: Network Isolation
                    // Use unshare to create a private network namespace (effectively disabling global network access)
                    // Note: This requires CLONE_NEWNET.
                    if libc::unshare(libc::CLONE_NEWNET) != 0 {
                        // We continue even if it fails, as some old kernels might not support it
                        // but ideally, we should log a warning if we had a logger here.
                    }

                    // RFC-0011 Linux-Shield: Prevent privilege escalation
                    // PR_SET_NO_NEW_PRIVS ensures that the process and its children cannot gain new privileges (e.g., via setuid)
                    if libc::prctl(libc::PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0 {
                        // Same here, fallback gracefully
                    }
                }

                Ok(())
            });
        }

        // Setup logging
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

        // Redirect stdout/stderr to log file for daemon mode
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
            std::thread::sleep(Duration::from_millis(100));
        }

        // Layer 3: Deep Liveness Probe & Handshake (RFC-0011 architectural requirement)
        log::info!("Zygote socket detected. Performing deep probe...");

        // 1. Connect and verify Ready greeting (handled by ZygoteStream::connect)
        let mut zygote_stream = ipc::ZygoteStream::connect(&self.socket_path)?;

        // 2. Perform Handshake
        log::debug!("Performing protocol handshake...");
        let handshake_cmd = ipc::ZygoteCommand::Handshake {
            version: ipc::PROTOCOL_VERSION,
            capabilities: vec!["map-protocol".to_string(), "async-reaper".to_string()],
        };
        let response = zygote_stream.send_command(&handshake_cmd, None)?;

        if let ipc::ZygoteResponse::Handshake {
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
        let status_cmd = ipc::ZygoteCommand::Status;
        let response = zygote_stream.send_command(&status_cmd, None)?;

        if let ipc::ZygoteResponse::Status { pid, .. } = response {
            if self.zygote_pid.is_some() && self.zygote_pid != Some(pid) {
                log::warn!(
                    "Deep probe PID mismatch: got {}, expected {} (Possible Shadow Trap, but continuing)",
                    pid,
                    self.zygote_pid.unwrap()
                );
            }
            log::info!("Zygote deep probe successful (PID: {}).", pid);
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
            let _ = ipc::send_command(&self.socket_path, ipc::ZygoteCommand::Shutdown, None);
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
    /// Either we own the process (zygote_pid set) or socket exists (external Zygote)
    pub fn is_running(&self) -> bool {
        self.zygote_pid.is_some() || self.socket_path.exists()
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
    #[allow(clippy::too_many_arguments)]
    pub fn spawn_worker(
        &self,
        script: &Path,
        args: &[&str],
        async_mode: bool,
        fast_mode: bool,
        bundle_path: Option<PathBuf>,
        project_root: Option<PathBuf>,
        max_bundle_size: Option<u64>,
        shm_file: Option<&std::fs::File>,
    ) -> Result<WorkerHandle> {
        if !self.is_running() {
            return Err(ZygoteError::NotRunning);
        }

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
        let exit_code_path =
            std::env::temp_dir().join(format!("velo-exit-{}-{}.tmp", pid, timestamp));

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
        let response = ipc::send_command(
            &self.socket_path,
            ipc::ZygoteCommand::Fork {
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
                env: Box::new(std::env::vars().collect()),
                shm_size,
            },
            fd_to_pass,
        )?;

        match response {
            ipc::ZygoteResponse::Forked {
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

                Ok(WorkerHandle {
                    pid: worker_pid,
                    stdout_path: Some(stdout_path),
                    stderr_path: Some(stderr_path),
                    exit_code_path: Some(exit_code_path),
                })
            }
            ipc::ZygoteResponse::Error { message } => Err(ZygoteError::ForkFailed(message)),
            _ => Err(ZygoteError::ProtocolError(
                "Unexpected response to Fork command".to_string(),
            )),
        }
    }

    #[cfg(not(unix))]
    pub fn spawn_worker(
        &self,
        _script: &Path,
        _args: &[&str],
        _async_mode: bool,
    ) -> Result<WorkerHandle> {
        Err(ZygoteError::NotSupported)
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
