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
use ipc::ZygoteResponse;
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::time::Duration;

/// Worker execution timeout in seconds
/// Long-running scripts may need a higher value; configurable is planned
pub const WORKER_TIMEOUT_SECS: u64 = 30;

/// Socket startup timeout in seconds
/// CI environments may need a higher value
pub const SOCKET_STARTUP_TIMEOUT_SECS: u64 = 10;

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
    crate::config::VeloConfig::from_pyproject_toml()
        .and_then(|c| c.zygote_worker_timeout)
        .unwrap_or(WORKER_TIMEOUT_SECS)
}

fn get_socket_timeout_secs() -> u64 {
    crate::config::VeloConfig::from_pyproject_toml()
        .and_then(|c| c.zygote_socket_timeout)
        .unwrap_or(SOCKET_STARTUP_TIMEOUT_SECS)
}

/// Get Zygote status
pub fn get_status() -> Result<ZygoteResponse> {
    use ipc::{default_socket_path, send_command, ZygoteCommand};

    let socket_path = default_socket_path();
    if !socket_path.exists() {
        return Err(ZygoteError::ConnectionFailed(
            "Socket file not found".to_string(),
        ));
    }

    send_command(&socket_path, ZygoteCommand::Status)
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

    // 2. Compiled-in path from CARGO_MANIFEST_DIR (dev builds)
    // This is set at compile time and points to the source directory
    let manifest_path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(ZYGOTE_MAIN);
    if manifest_path.exists() {
        return Ok(manifest_path.canonicalize().unwrap_or(manifest_path));
    }

    // 3. Search relative to executable (installed builds)
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
         - Relative to executable\n\
         - ~/.local/share/velo/\n\
         - /usr/local/share/velo/\n\
         - Current directory\n\
         Set VELO_ZYGOTE_PATH to override.",
        env!("CARGO_MANIFEST_DIR")
    )))
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

        // Detach from parent process group so Zygote survives CLI exit
        #[cfg(unix)]
        unsafe {
            use std::os::unix::process::CommandExt;
            cmd.pre_exec(|| {
                // Create new session (setsid) to detach from parent
                libc::setsid();
                Ok(())
            });
        }

        // Redirect stdout/stderr to null for daemon mode
        // Worker output goes through a different channel (not Zygote's stdout)
        use std::process::Stdio;
        cmd.stdout(Stdio::null());
        cmd.stderr(Stdio::null());

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
        while !self.socket_path.exists() {
            if start.elapsed() > timeout {
                self.stop()?;
                return Err(ZygoteError::StartFailed(format!(
                    "Timeout waiting for Zygote socket after {}s",
                    timeout_secs
                )));
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
    /// Only sends Shutdown if this launcher owns the Zygote process
    pub fn stop(&mut self) -> Result<()> {
        // Only stop if we OWN the Zygote process (not just connecting to existing one)
        if self.zygote_process.is_none() {
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
            },
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
