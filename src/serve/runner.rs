//! Server runner - uvicorn wrapper with Zygote integration
//!
//! Manages uvicorn subprocess with optional Zygote pre-warming.
//!
//! ## Safety
//!
//! This module uses RAII patterns to ensure subprocess cleanup:
//! - `ManagedChild` kills and waits for child on Drop
//! - `ShutdownCoordinator` handles SIGTERM/SIGINT gracefully

use anyhow::Result;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitStatus, Stdio};

use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

use crate::serve::config::ServeArgs;
use crate::serve::error::ServeError;
use crate::serve::framework::{detect_framework, get_preload_modules};
use crate::zygote::ZygoteLauncher;

// ============================================================================
// Security helpers (ADR D3, D4)
// ============================================================================

/// SEC-P0-005: Remove dangerous environment variables before subprocess spawn (ADR D3)
///
/// Removes variables that could hijack Python execution or library loading.
fn sanitize_subprocess_env(cmd: &mut Command) {
    const DANGEROUS: &[&str] = &[
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "DYLD_INSERT_LIBRARIES", // macOS
    ];

    for var in DANGEROUS {
        cmd.env_remove(var);
    }
}

/// MAC-P0-002: Reset signal handlers in child process (ADR D4)
///
/// Prevents zombie workers when uvicorn/gunicorn forks workers.
#[cfg(target_os = "macos")]
fn apply_macos_signal_reset(cmd: &mut Command) {
    use std::os::unix::process::CommandExt;

    unsafe {
        cmd.pre_exec(|| {
            // Reset SIGINT/SIGTERM to default in child
            libc::signal(libc::SIGINT, libc::SIG_DFL);
            libc::signal(libc::SIGTERM, libc::SIG_DFL);
            Ok(())
        });
    }
}

// ============================================================================
// ManagedChild - RAII wrapper for subprocess (D2, RFC §4.9.3)
// ============================================================================

/// RAII wrapper for child process.
///
/// Ensures process is killed and reaped on Drop (including panic).
/// Also manages PID file cleanup.
pub struct ManagedChild {
    child: Child,
    pid_file: Option<PathBuf>,
}

impl ManagedChild {
    /// Spawn a new managed child process.
    ///
    /// # Arguments
    /// * `cmd` - Command to spawn
    /// * `pid_file` - Optional PID file path to create
    pub fn spawn(mut cmd: Command, pid_file: Option<PathBuf>) -> Result<Self, ServeError> {
        let child = cmd.spawn().map_err(|e| ServeError::ServerStartFailed {
            reason: e.to_string(),
            exit_code: 1,
        })?;

        // Write PID file if requested (SEC-P0-003: use O_EXCL)
        if let Some(ref path) = pid_file {
            Self::write_pid_file_safe(path, child.id())?;
        }

        Ok(Self { child, pid_file })
    }

    /// Write PID file safely using O_EXCL to prevent TOCTOU attacks.
    #[cfg(unix)]
    fn write_pid_file_safe(path: &Path, pid: u32) -> Result<(), ServeError> {
        use std::io::Write;
        use std::os::unix::fs::OpenOptionsExt;

        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true) // O_EXCL: fail if exists
            .mode(0o644)
            .open(path)
            .map_err(|_| ServeError::PidFileExists {
                path: path.to_path_buf(),
            })?;

        writeln!(file, "{}", pid).map_err(ServeError::SignalError)?;
        Ok(())
    }

    #[cfg(not(unix))]
    fn write_pid_file_safe(path: &Path, pid: u32) -> Result<(), ServeError> {
        use std::io::Write;

        if path.exists() {
            return Err(ServeError::PidFileExists {
                path: path.to_path_buf(),
            });
        }

        let mut file = std::fs::File::create(path).map_err(ServeError::SignalError)?;
        writeln!(file, "{}", pid).map_err(ServeError::SignalError)?;
        Ok(())
    }

    /// Wait for the child process to exit.
    pub fn wait(&mut self) -> Result<ExitStatus, ServeError> {
        self.child.wait().map_err(ServeError::SignalError)
    }

    /// Wait for the child with timeout for graceful shutdown.
    ///
    /// Returns Ok(Some(status)) if exited within timeout.
    /// Returns Ok(None) if timeout expired (caller should force kill).
    pub fn wait_timeout(&mut self, timeout: Duration) -> Result<Option<ExitStatus>, ServeError> {
        let start = Instant::now();
        let poll_interval = Duration::from_millis(50);

        loop {
            match self.child.try_wait() {
                Ok(Some(status)) => return Ok(Some(status)),
                Ok(None) => {
                    if start.elapsed() >= timeout {
                        return Ok(None);
                    }
                    std::thread::sleep(poll_interval);
                }
                Err(e) => return Err(ServeError::SignalError(e)),
            }
        }
    }

    /// Send SIGTERM to the child process (graceful shutdown).
    #[cfg(unix)]
    pub fn terminate(&self) -> Result<(), ServeError> {
        // Send SIGTERM
        let pid = self.child.id() as i32;
        unsafe {
            libc::kill(pid, libc::SIGTERM);
        }
        Ok(())
    }

    #[cfg(not(unix))]
    pub fn terminate(&mut self) -> Result<(), ServeError> {
        self.child.kill().map_err(ServeError::SignalError)
    }

    /// Force kill the child process.
    pub fn kill(&mut self) -> Result<(), ServeError> {
        self.child.kill().map_err(ServeError::SignalError)?;
        // Reap to prevent zombie
        let _ = self.child.wait();
        Ok(())
    }

    /// Get the child's PID.
    pub fn id(&self) -> u32 {
        self.child.id()
    }
}

impl Drop for ManagedChild {
    fn drop(&mut self) {
        // Ensure child is killed and reaped on panic or normal exit
        let _ = self.child.kill();
        let _ = self.child.wait();

        // Cleanup PID file
        if let Some(ref path) = self.pid_file {
            let _ = std::fs::remove_file(path);
        }
    }
}

// ============================================================================
// Event Bus Definitions (Recommendation #1)
// ============================================================================

/// Events that can wake up the main server loop
#[derive(Debug)]
pub enum ServerEvent {
    /// Signal received (SIGINT, SIGTERM, SIGCHLD)
    Signal(i32),
    /// Worker thread exit (only used on Windows/non-Unix)
    #[allow(dead_code)]
    WorkerExit,
}

/// Spawns a thread to forward signals to the event bus.
///
/// On Unix, we listen for:
/// - SIGINT (Ctrl+C)
/// - SIGTERM (Graceful shutdown)
/// - SIGCHLD (Child process exit)
#[cfg(unix)]
fn spawn_signal_forwarder(tx: mpsc::Sender<ServerEvent>) -> Result<(), ServeError> {
    use signal_hook::consts::{SIGCHLD, SIGINT, SIGTERM};
    use signal_hook::iterator::Signals;

    let mut signals = Signals::new([SIGINT, SIGTERM, SIGCHLD]).map_err(ServeError::SignalError)?;

    thread::spawn(move || {
        for signal in signals.forever() {
            if tx.send(ServerEvent::Signal(signal)).is_err() {
                // Receiver dropped, exit thread
                break;
            }
        }
    });

    Ok(())
}

#[cfg(not(unix))]
fn spawn_signal_forwarder(tx: mpsc::Sender<ServerEvent>) -> Result<(), ServeError> {
    // Windows implementation primarily relies on Ctrl-C handler
    // Note: This is simplified compared to Unix SIGCHLD
    let tx_clone = tx.clone();
    ctrlc::set_handler(move || {
        // Use an arbitrary signal number for Ctrl-C on Windows equivalent to SIGINT
        let _ = tx_clone.send(ServerEvent::Signal(2)); // 2 = SIGINT
    })
    .map_err(|e| ServeError::ServerStartFailed {
        reason: format!("Failed to set ctrl-c handler: {}", e),
        exit_code: 1,
    })?;

    Ok(())
}

/// Run the ASGI/WSGI application via uvicorn/gunicorn
///
/// # Arguments
/// * `args` - Serve command arguments
/// * `python_path` - Path to Python interpreter
/// * `project_dir` - Project directory
#[cfg(unix)]
pub fn run_server(args: &ServeArgs, python_path: &Path, project_dir: &Path) -> Result<()> {
    use crate::serve::framework::{Server, check_server_installed, get_server_type};

    // Step 1: Validate app format
    let (module, _attr) = args.parse_app()?;

    // Step 2: Detect framework FIRST (shows user Velo understands their project)
    let framework = detect_framework(module, project_dir);
    let preload_modules = get_preload_modules(framework);

    // Step 3: Select server based on framework (D4)
    let server = get_server_type(framework);

    // Show framework detection result
    if framework != crate::serve::framework::Framework::Unknown {
        eprintln!(
            "🔍 Detected: {} → {} (auto-preload: {})",
            framework,
            server,
            preload_modules.join(", ")
        );
    }

    // Step 4: Check server is installed
    if !check_server_installed(server, python_path) {
        eprintln!("❌ Missing dependency: {}", server);
        eprintln!();
        eprintln!("{} is required to run {} applications.", server, framework);
        eprintln!("To fix:");
        eprintln!("    {}", server.install_hint());
        std::process::exit(1);
    }

    // Step 5: Setup Event Bus (Recommendation #1)
    let (tx, rx) = mpsc::channel();
    spawn_signal_forwarder(tx.clone())?;

    // Step 6: Start server
    eprintln!("🚀 Starting server...");
    eprintln!("   App:       {}", args.app);
    eprintln!("   Server:    {}", server);
    eprintln!("   Bind:      {}:{}", args.host, args.port);
    eprintln!("   Workers:   {}", args.workers);
    eprintln!("   Timeout:   {}s", args.timeout);
    if args.reload {
        eprintln!("   Reload:    enabled");
    }

    // Start Zygote if enabled and we have preload modules
    if args.use_zygote && !preload_modules.is_empty() && crate::zygote::is_supported() {
        let socket_path = crate::zygote::ipc::default_socket_path();

        if !socket_path.exists() {
            eprintln!("⚡ Pre-warming Zygote with {} modules...", framework);
            let mut launcher =
                ZygoteLauncher::new(socket_path).with_python(python_path.to_path_buf());

            if let Err(e) = launcher.start(&preload_modules) {
                eprintln!("⚠️  Zygote pre-warm failed: {}", e);
                eprintln!("   Continuing without Zygote optimization");
            } else {
                eprintln!("✅ Zygote ready");
                // Keep Zygote alive
                std::mem::forget(launcher);
            }
        } else {
            eprintln!("⚡ Using existing Zygote");
        }
    }

    // Build server command based on server type
    let mut cmd = Command::new(python_path);
    cmd.arg("-m").arg(server.module_name());

    match server {
        Server::Uvicorn => {
            cmd.arg(&args.app)
                .arg("--host")
                .arg(&args.host)
                .arg("--port")
                .arg(args.port.to_string());

            if args.workers > 1 {
                cmd.arg("--workers").arg(args.workers.to_string());
            }
            if args.reload {
                cmd.arg("--reload");
            }
        }
        Server::Gunicorn => {
            // Gunicorn uses different arg format
            cmd.arg("--bind")
                .arg(format!("{}:{}", args.host, args.port))
                .arg("--workers")
                .arg(args.workers.to_string())
                .arg("--timeout")
                .arg(args.timeout.to_string());

            if args.reload {
                cmd.arg("--reload");
            }
            cmd.arg(&args.app);
        }
    }

    // SEC-P0-005: Remove dangerous environment variables (ADR D3)
    sanitize_subprocess_env(&mut cmd);

    // MAC-P0-002: Reset signal handlers in child (ADR D4)
    #[cfg(target_os = "macos")]
    apply_macos_signal_reset(&mut cmd);

    // Set working directory and inherit stdio
    cmd.current_dir(project_dir)
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());

    eprintln!();

    // Spawn with ManagedChild for RAII cleanup (D2)
    let mut child = ManagedChild::spawn(cmd, args.pid_file.clone())
        .map_err(|e| anyhow::anyhow!("Failed to start server: {}", e))?;

    eprintln!("✅ Server started (PID: {})", child.id());

    // CN-P0-001: Spawn health server if --health-bind is set (ADR D2)
    let _health_server = if let Some(ref health_bind) = args.health_bind {
        use crate::serve::health::HealthServer;

        // Initially not ready, will be set after first successful response
        let ready = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));

        match HealthServer::spawn(health_bind, std::sync::Arc::clone(&ready)) {
            Ok(server) => {
                eprintln!("🏥 Health server: http://{}/healthz", health_bind);
                // Mark as ready (in real impl, we'd wait for first HTTP response)
                ready.store(true, std::sync::atomic::Ordering::SeqCst);
                Some(server)
            }
            Err(e) => {
                eprintln!("⚠️  Failed to start health server: {}", e);
                None
            }
        }
    } else {
        None
    };

    // Main loop: Wait for Events (Zero Busy Wait)
    loop {
        // Block until event received
        match rx.recv() {
            Ok(ServerEvent::Signal(sig)) => {
                match sig {
                    signal_hook::consts::SIGCHLD => {
                        // Optimistic: Child might have exited
                        // Only try_wait() on SIGCHLD to avoid polling
                        match child.wait_timeout(Duration::from_millis(0)) {
                            Ok(Some(status)) => {
                                if !status.success() {
                                    let code = status.code().unwrap_or(1);
                                    if code == 1 {
                                        eprintln!();
                                        eprintln!(
                                            "💡 Tip: If the app failed to import, check for syntax errors or missing dependencies."
                                        );
                                    }
                                    std::process::exit(code);
                                }
                                return Ok(());
                            }
                            Ok(None) => {
                                // False alarm, child still running (or another child)
                                continue;
                            }
                            Err(e) => anyhow::bail!("Error waiting for server: {}", e),
                        }
                    }
                    signal_hook::consts::SIGINT | signal_hook::consts::SIGTERM => {
                        eprintln!();
                        eprintln!("🛑 Shutdown signal received, waiting for graceful shutdown...");

                        if let Err(e) = child.terminate() {
                            eprintln!("⚠️  Failed to send SIGTERM: {}", e);
                        }

                        // Wait for graceful shutdown with timeout
                        let timeout = Duration::from_secs(args.timeout);
                        match child.wait_timeout(timeout) {
                            Ok(Some(_)) => {
                                eprintln!("✅ Server shut down gracefully");
                                return Ok(());
                            }
                            Ok(None) => {
                                eprintln!(
                                    "⚠️  Graceful shutdown timed out after {}s, force killing...",
                                    args.timeout
                                );
                                if let Err(e) = child.kill() {
                                    eprintln!("❌ Failed to kill server: {}", e);
                                }
                                return Ok(());
                            }
                            Err(e) => anyhow::bail!("Error waiting for shutdown: {}", e),
                        }
                    }
                    _ => {}
                }
            }
            Ok(ServerEvent::WorkerExit) => {
                // Not used in Unix path currently, but handle for future
                return Ok(());
            }
            Err(_) => {
                // Channel closed, unexpected
                anyhow::bail!("Event bus closed unexpectedly");
            }
        }
    }
}

#[cfg(not(unix))]
pub fn run_server(args: &ServeArgs, python_path: &Path, project_dir: &Path) -> Result<()> {
    // Windows: run uvicorn without Zygote
    eprintln!("🚀 Starting server (Zygote not supported on Windows)...");
    eprintln!("   App:     {}", args.app);
    eprintln!("   Bind:    {}:{}", args.host, args.port);
    eprintln!("   Workers: {}", args.workers);

    let mut cmd = Command::new(python_path);
    cmd.arg("-m")
        .arg("uvicorn")
        .arg(&args.app)
        .arg("--host")
        .arg(&args.host)
        .arg("--port")
        .arg(args.port.to_string());

    if args.workers > 1 {
        cmd.arg("--workers").arg(args.workers.to_string());
    }

    if args.reload {
        cmd.arg("--reload");
    }

    cmd.current_dir(project_dir)
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());

    let status = cmd
        .status()
        .context("Failed to start uvicorn. Is it installed?")?;

    if !status.success() {
        std::process::exit(status.code().unwrap_or(1));
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    // ========================================================================
    // ManagedChild tests (D2) - Note: These require spawning actual processes
    // ========================================================================

    #[test]
    fn test_managed_child_spawn_success() {
        // Spawn a simple command that exits immediately
        let mut cmd = Command::new("echo");
        cmd.arg("test");
        cmd.stdout(Stdio::null());

        let child = ManagedChild::spawn(cmd, None);
        assert!(child.is_ok(), "Should successfully spawn echo command");
    }

    #[test]
    fn test_managed_child_id() {
        let mut cmd = Command::new("sleep");
        cmd.arg("10");

        let child = ManagedChild::spawn(cmd, None);
        assert!(child.is_ok());
        let child = child.unwrap();

        assert!(child.id() > 0, "Child should have a valid PID");
    }

    #[test]
    fn test_managed_child_wait_timeout_returns_none_for_running() {
        let mut cmd = Command::new("sleep");
        cmd.arg("10");

        let mut child = ManagedChild::spawn(cmd, None).unwrap();

        // Should return None because process is still running
        let result = child.wait_timeout(Duration::from_millis(100));
        assert!(result.is_ok());
        assert!(
            result.unwrap().is_none(),
            "Should return None for running process"
        );
    }

    #[test]
    fn test_managed_child_terminate() {
        let mut cmd = Command::new("sleep");
        cmd.arg("60");

        let mut child = ManagedChild::spawn(cmd, None).unwrap();

        // Terminate should succeed
        let result = child.terminate();
        assert!(result.is_ok(), "Terminate should succeed");

        // Wait for process to exit
        let wait_result = child.wait_timeout(Duration::from_secs(5));
        assert!(wait_result.is_ok());
        // Process should have exited after SIGTERM
    }

    #[test]
    fn test_managed_child_kill() {
        let mut cmd = Command::new("sleep");
        cmd.arg("60");

        let mut child = ManagedChild::spawn(cmd, None).unwrap();

        // Kill should succeed
        let result = child.kill();
        assert!(result.is_ok(), "Kill should succeed");
    }

    // ========================================================================
    // ManagedChild PID file tests (D2, SEC-P0-003)
    // ========================================================================

    #[test]
    fn test_managed_child_creates_pid_file() {
        let temp_dir = tempfile::tempdir().unwrap();
        let pid_file = temp_dir.path().join("test.pid");

        let mut cmd = Command::new("sleep");
        cmd.arg("10");

        let child = ManagedChild::spawn(cmd, Some(pid_file.clone())).unwrap();

        // PID file should exist
        assert!(pid_file.exists(), "PID file should be created");

        // PID file should contain the correct PID
        let content = std::fs::read_to_string(&pid_file).unwrap();
        let pid: u32 = content.trim().parse().unwrap();
        assert_eq!(pid, child.id(), "PID file should contain correct PID");
    }

    #[test]
    fn test_managed_child_removes_pid_file_on_drop() {
        let temp_dir = tempfile::tempdir().unwrap();
        let pid_file = temp_dir.path().join("test.pid");

        {
            let mut cmd = Command::new("sleep");
            cmd.arg("1");
            let _child = ManagedChild::spawn(cmd, Some(pid_file.clone())).unwrap();
            assert!(
                pid_file.exists(),
                "PID file should exist while child is alive"
            );
            // child is dropped here
        }

        assert!(!pid_file.exists(), "PID file should be removed on drop");
    }
}
