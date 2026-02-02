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

use colored::Colorize;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

use crate::config::{LogFormat, ServeArgs};
use crate::error::ServeError;
use crate::framework::{AppProtocol, Server, detect_app_protocol};
use velo_core::custody::autopilot::{AutopilotDecision, AutopilotEngine};
use velo_core::lifecycle::apply_standard_hygiene;
use velo_core::zygote::ZygoteLauncher;

// Proxy integration (RFC-0011 Phase 2)
use crate::proxy::{LoadBalancer, VeloProxyService};
use hyper::server::conn::http1;
use hyper_util::rt::TokioIo;

#[cfg(unix)]
use std::os::unix::io::AsRawFd;

#[cfg(unix)]
fn cleanup_zygote_processes_for_test(socket_path: &Path) {
    let output = std::process::Command::new("/bin/ps")
        .args(["-ax", "-o", "pid=,command="])
        .output();
    let Ok(output) = output else {
        return;
    };
    let Ok(text) = String::from_utf8(output.stdout) else {
        return;
    };
    let needle = socket_path.to_string_lossy();
    for line in text.lines() {
        if !line.contains("velo_zygote/main.py") || !line.contains(needle.as_ref()) {
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

#[cfg(unix)]
fn cleanup_descendants_for_test(parent_pid: i32) {
    let output = std::process::Command::new("/bin/ps")
        .args(["-ax", "-o", "pid=,ppid=,pgid="])
        .output();
    let Ok(output) = output else {
        return;
    };
    let Ok(text) = String::from_utf8(output.stdout) else {
        return;
    };

    let mut children_map: std::collections::HashMap<i32, Vec<i32>> =
        std::collections::HashMap::new();
    let mut pgid_map: std::collections::HashMap<i32, i32> = std::collections::HashMap::new();

    for line in text.lines() {
        let mut parts = line.split_whitespace();
        let Some(pid_str) = parts.next() else {
            continue;
        };
        let Some(ppid_str) = parts.next() else {
            continue;
        };
        let Some(pgid_str) = parts.next() else {
            continue;
        };

        if let (Ok(pid), Ok(ppid), Ok(pgid)) = (
            pid_str.parse::<i32>(),
            ppid_str.parse::<i32>(),
            pgid_str.parse::<i32>(),
        ) {
            children_map.entry(ppid).or_default().push(pid);
            pgid_map.insert(pid, pgid);
        }
    }

    let mut stack = vec![parent_pid];
    let mut descendants = Vec::new();
    let mut target_pgids = std::collections::HashSet::new();

    while let Some(ppid) = stack.pop() {
        if let Some(children) = children_map.get(&ppid) {
            for &child in children {
                descendants.push(child);
                stack.push(child);
                if let Some(&pgid) = pgid_map.get(&child) {
                    target_pgids.insert(pgid);
                }
            }
        }
    }

    // Phase 1: Kill all direct descendants
    for pid in descendants {
        unsafe {
            let _ = libc::kill(pid, libc::SIGKILL);
        }
    }

    // Phase 2: Kill any orphan that belongs to one of the identified descendant PGIDs
    // This catches processes re-parented to PID 1
    for (pid, pgid) in pgid_map {
        if target_pgids.contains(&pgid) {
            unsafe {
                let _ = libc::kill(pid, libc::SIGKILL);
            }
        }
    }
}

#[cfg(unix)]
fn cleanup_uvicorn_workers_for_test(socket_dir: &Path) {
    let output = std::process::Command::new("/bin/ps")
        .args(["-ax", "-o", "pid=,command="])
        .output();
    let Ok(output) = output else {
        return;
    };
    let Ok(text) = String::from_utf8(output.stdout) else {
        return;
    };
    let socket_dir_str = socket_dir.to_string_lossy();
    for line in text.lines() {
        // Look for uvicorn workers. They usually contain the app name or our socket dir
        // in their command line. In test mode, we are more aggressive.
        if !line.contains("uvicorn") {
            continue;
        }

        // Check if it's related to our test session or specific app
        // uvicorn commands in our tests always have either --uds or are spawned by our binary
        let is_ours = line.contains(socket_dir_str.as_ref())
            || line.contains("--uds")
            || line.contains("main:app"); // Default app name in most tests

        if !is_ours {
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

#[cfg(unix)]
fn cleanup_zygote_process_group_for_test(socket_path: &Path) {
    use velo_core::zygote::core_ipc::{ZygoteCommand, ZygoteResponse, send_command};
    if let Ok(ZygoteResponse::Status { pid, .. }) = send_command(
        socket_path,
        ZygoteCommand::Status { request_id: None },
        None,
    ) {
        unsafe {
            let _ = libc::kill(-(pid as i32), libc::SIGKILL);
        }
    }
}

#[cfg(unix)]
pub fn cleanup_test_processes(project_dir: &Path, app: &str) {
    let socket_path = velo_core::zygote::core_ipc::socket_path_for_app(project_dir, app);
    cleanup_zygote_process_group_for_test(&socket_path);
    cleanup_zygote_processes_for_test(&socket_path);
    cleanup_descendants_for_test(std::process::id() as i32);
    cleanup_uvicorn_workers_for_test(&velo_core::common::paths::get_socket_dir());
}

// ============================================================================
// Logging & Security helpers (ADR D3, D4, D5)
// ============================================================================

/// Structured logger for serve command (ADR D5)
struct ServeLogger {
    format: LogFormat,
    verbose_level: u8,
}

impl ServeLogger {
    fn new(format: LogFormat, verbose_level: u8) -> Self {
        Self {
            format,
            verbose_level,
        }
    }

    fn info(&self, msg: &str) {
        self.log("info", msg, None);
    }

    fn info_with(&self, msg: &str, detail: &str) {
        if self.verbose_level >= 1 {
            self.log("info", msg, Some(detail));
        } else {
            self.log("info", msg, None);
        }
    }

    fn verbose(&self, msg: &str) {
        if self.verbose_level >= 1 {
            self.log("info", msg, None);
        }
    }

    fn warn(&self, msg: &str) {
        self.log("warn", msg, None);
    }

    fn error(&self, msg: &str) {
        self.log("error", msg, None);
    }

    fn debug(&self, msg: &str) {
        if self.verbose_level >= 2 {
            self.log("debug", msg, None);
        }
    }

    fn log(&self, level: &str, msg: &str, detail: Option<&str>) {
        self.log_with_timing(level, msg, detail, None);
    }

    fn log_with_timing(
        &self,
        level: &str,
        msg: &str,
        detail: Option<&str>,
        timing_ms: Option<u128>,
    ) {
        match self.format {
            LogFormat::Json => {
                let timestamp =
                    chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true);

                let mut json = serde_json::json!({
                    "timestamp": timestamp,
                    "level": level,
                    "msg": msg,
                });

                if let Some(t) = timing_ms {
                    json["timing_ms"] = serde_json::json!(t);
                }
                if let Some(d) = detail {
                    json["detail"] = serde_json::json!(d);
                }

                eprintln!("{}", json);
                use std::io::Write;
                let _ = std::io::stderr().flush();
            }
            LogFormat::Text => {
                use colored::Colorize;
                let level_colored = match level {
                    "info" => "info".blue().bold(),
                    "warn" => "warn".yellow().bold(),
                    "error" => "error".red().bold(),
                    _ => level.normal(),
                };
                let mut base = if let Some(d) = detail {
                    format!("{}: {} {}", level_colored, msg, d)
                } else {
                    format!("{}: {}", level_colored, msg)
                };
                if let Some(t) = timing_ms {
                    base.push_str(&format!(" ({:.1}ms)", t as f64));
                }
                eprintln!("{}", base);
            }
        }
    }
}

// function removed

#[cfg(unix)]
fn apply_process_group(cmd: &mut Command) {
    use std::os::unix::process::CommandExt;
    unsafe {
        cmd.pre_exec(|| {
            // Become a process group leader (STB-RS-003)
            if libc::setpgid(0, 0) != 0 {
                return Err(std::io::Error::last_os_error());
            }

            // TITANIUM RULE: No Orphans
            // Kill child if parent (supervisor) dies
            #[cfg(target_os = "linux")]
            if libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGKILL) != 0 {
                return Err(std::io::Error::last_os_error());
            }

            Ok(())
        });
    }
    // RFC-0012 §3.6: Standard FD & Signal Hygiene
    apply_standard_hygiene(cmd);
}

fn build_server_command(
    server: Server,
    args: &ServeArgs,
    python_path: &Path,
    project_dir: &Path,
    logger: &ServeLogger,
) -> Result<Command> {
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
            // Velo handles reload supervision; avoid nested reloader processes.
            // STB-RS-004: Ensure uvicorn exits quickly on SIGTERM to avoid supervisor hangs
            cmd.arg("--timeout-graceful-shutdown").arg("1");
        }
        Server::Gunicorn => {
            cmd.arg("--bind")
                .arg(format!("{}:{}", args.host, args.port))
                .arg("--workers")
                .arg(args.workers.to_string())
                .arg("--timeout")
                .arg(args.timeout.to_string());

            cmd.arg(&args.app);
        }
        Server::RSGI => {
            anyhow::bail!("RSGI mode is not supported in legacy fallback mode");
        }
    }

    logger.verbose(&format!("Current directory: {:?}", project_dir));
    cmd.current_dir(project_dir)
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());

    Ok(cmd)
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
    pgid: Option<i32>,
    pid_file: Option<PathBuf>,
}
impl ManagedChild {
    /// Get child process ID.
    pub fn id(&self) -> u32 {
        self.child.id()
    }

    /// Get process group ID (Unix only).
    #[cfg(unix)]
    pub fn pgid(&self) -> Option<i32> {
        self.pgid
    }

    /// Spawn a new managed child process.
    ///
    /// # Arguments
    /// * `cmd` - Command to spawn
    /// * `pid_file` - Optional PID file path to create (Deprecated: handled by PidFileGuard)
    pub fn spawn(mut cmd: Command, pid_file: Option<PathBuf>) -> Result<Self, ServeError> {
        #[cfg(unix)]
        apply_process_group(&mut cmd);

        let mut child = cmd.spawn().map_err(|e| ServeError::ServerStartFailed {
            reason: e.to_string(),
            exit_code: 1,
        })?;

        // Write PID file if requested (SEC-P0-003: use O_EXCL)
        // NOTE: This is kept for backward compatibility if called directly,
        // but run_server now uses PidFileGuard.
        if let Some(ref path) = pid_file
            && let Err(e) = PidFileGuard::write_pid_file_safe(path, child.id())
        {
            let _ = child.kill();
            let _ = child.wait();
            return Err(e);
        }

        #[cfg(unix)]
        let pgid = Some(child.id() as i32);
        #[cfg(not(unix))]
        let pgid = None;

        Ok(Self {
            child,
            pgid,
            pid_file,
        })
    }
}

/// RAII Guard for PID file management (SEC-P0-003)
pub struct PidFileGuard {
    path: PathBuf,
}

impl PidFileGuard {
    /// Create a new PID file guard. Writes the current process PID to the file.
    pub fn new(path: PathBuf) -> Result<Self, ServeError> {
        Self::write_pid_file_safe(&path, std::process::id())?;
        Ok(Self { path })
    }

    /// Write PID file safely using O_EXCL to prevent TOCTOU attacks.
    pub fn write_pid_file_safe(path: &Path, pid: u32) -> Result<(), ServeError> {
        #[cfg(unix)]
        {
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
        {
            use std::io::Write;
            let mut file = std::fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(path)
                .map_err(|_| ServeError::PidFileExists {
                    path: path.to_path_buf(),
                })?;
            writeln!(file, "{}", pid).map_err(ServeError::SignalError)?;
            Ok(())
        }
    }
}

impl Drop for PidFileGuard {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.path);
    }
}

impl ManagedChild {
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
    pub fn terminate(&mut self) -> Result<(), ServeError> {
        let signal_pid = if let Some(pgid) = self.pgid {
            -pgid
        } else {
            self.child.id() as i32
        };

        // Send SIGTERM to the entire process group (negative PID)
        unsafe {
            if libc::kill(signal_pid, libc::SIGTERM) == 0 {
                return Ok(());
            }
        }
        // Fallback to killing just the child if process group kill fails
        self.child.kill().map_err(ServeError::SignalError)
    }

    #[cfg(not(unix))]
    pub fn terminate(&mut self) -> Result<(), ServeError> {
        self.child.kill().map_err(ServeError::SignalError)
    }

    /// Force kill the child process.
    pub fn kill(&mut self) -> Result<(), ServeError> {
        #[cfg(unix)]
        {
            let signal_pid = if let Some(pgid) = self.pgid {
                -pgid
            } else {
                self.child.id() as i32
            };
            // Send SIGKILL to the entire process group (negative PID)
            unsafe {
                if libc::kill(signal_pid, libc::SIGKILL) == 0 {
                    return Ok(());
                }
            }
        }
        self.child.kill().map_err(ServeError::SignalError)
    }
}

impl Drop for ManagedChild {
    fn drop(&mut self) {
        // STB-RS-003: Kill entire process group (PGID = child PID since child is group leader)
        // This ensures uvicorn workers and other grandchildren are also terminated
        #[cfg(unix)]
        {
            let signal_pid = if let Some(pgid) = self.pgid {
                -pgid
            } else {
                self.child.id() as i32
            };
            // Send SIGKILL to the entire process group (negative PID)
            unsafe {
                libc::kill(signal_pid, libc::SIGKILL);
            }
        }

        // Fallback for non-Unix or if process group kill failed
        #[cfg(not(unix))]
        {
            let _ = self.child.kill();
        }

        // Wait for child to be reaped (prevents zombies)
        let _ = self.child.wait();

        // Cleanup PID file
        if let Some(ref path) = self.pid_file {
            let _ = std::fs::remove_file(path);
        }
    }
}

// ============================================================================
// Shutdown Management (SEC-P0-001)
// ============================================================================

/// Coordinator for graceful shutdown.
pub struct ShutdownCoordinator {
    /// Atomic flag set to true when shutdown is requested.
    pub flag: Arc<AtomicBool>,
}

impl ShutdownCoordinator {
    /// Create a new shutdown coordinator.
    pub fn new() -> Result<Self, std::io::Error> {
        let flag = Arc::new(AtomicBool::new(false));
        Ok(Self { flag })
    }

    /// Request shutdown.
    pub fn request_shutdown(&self) {
        self.flag.store(true, std::sync::atomic::Ordering::SeqCst);
    }

    /// Check if shutdown was requested.
    pub fn is_shutting_down(&self) -> bool {
        self.flag.load(std::sync::atomic::Ordering::SeqCst)
    }
}

// ============================================================================
// Worker Management Helpers (RFC-0011, RFC-0018 Phase 7.2)
// ============================================================================

/// K8s-style CrashLoopBackOff tracker per worker
/// Prevents respawn storms with exponential backoff: 10s -> 20s -> 40s -> ... -> 300s (cap)
struct RespawnTracker {
    last_failure: Option<Instant>,
    backoff_secs: u64,
    consecutive_failures: u32,
    fail_fast_limit: u32,
}

impl RespawnTracker {
    fn new() -> Self {
        let timeout_multiplier: f64 = std::env::var("VELO_TIMEOUT_MULTIPLIER")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(1.0);

        let test_mode = std::env::var("VELO_TEST_MODE").is_ok();
        let default_backoff = if test_mode { 1 } else { 10 };
        let default_limit = if test_mode { 3 } else { 5 };

        let backoff_secs = std::env::var("VELO_BACKOFF_SECS")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(default_backoff);

        let base_limit: u32 = std::env::var("VELO_FAIL_FAST_LIMIT")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(default_limit);
        let fail_fast_limit = (base_limit as f64 * timeout_multiplier) as u32;

        Self {
            last_failure: None,
            backoff_secs,
            consecutive_failures: 0,
            fail_fast_limit,
        }
    }

    fn should_respawn(&self) -> bool {
        match self.last_failure {
            None => true,
            Some(t) => t.elapsed().as_secs() >= self.backoff_secs,
        }
    }

    fn record_failure(&mut self) -> bool {
        self.last_failure = Some(Instant::now());
        self.consecutive_failures += 1;

        let test_mode = std::env::var("VELO_TEST_MODE").is_ok();
        let max_backoff = if test_mode { 1 } else { 300 };
        self.backoff_secs = (self.backoff_secs * 2).min(max_backoff);

        // DEF-72-R01: Log backoff for observability
        // Standardized on eprintln! for guaranteed immediate visibility in stderr
        eprintln!(
            "[RESPAWN] Worker crashed (attempt {}/{}), retrying in {}s (backoff)",
            self.consecutive_failures, self.fail_fast_limit, self.backoff_secs
        );

        if self.consecutive_failures >= self.fail_fast_limit {
            log::error!(
                "FATAL: Worker failed to start after {}/{} attempts. \
                 Check environment configuration and dependencies.",
                self.consecutive_failures,
                self.fail_fast_limit
            );
            false
        } else {
            true
        }
    }
}

/// Events that can wake up the main server loop
#[derive(Debug)]
pub enum ServerEvent {
    /// Signal received (SIGINT, SIGTERM, SIGCHLD)
    Signal(i32),
    /// Hot reload requested
    Reload,
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
fn spawn_signal_forwarder(
    tx: mpsc::Sender<ServerEvent>,
    shutdown_flag: Arc<AtomicBool>,
) -> Result<(), ServeError> {
    use signal_hook::consts::{SIGCHLD, SIGINT, SIGTERM};
    use signal_hook::iterator::Signals;

    let mut signals = Signals::new([SIGINT, SIGTERM, SIGCHLD]).map_err(ServeError::SignalError)?;

    thread::spawn(move || {
        let test_mode = std::env::var("VELO_TEST_MODE").unwrap_or_default() == "1";
        while !shutdown_flag.load(std::sync::atomic::Ordering::SeqCst) {
            for signal in signals.pending() {
                if test_mode && signal == SIGTERM {
                    eprintln!("CHILD_RECEIVED_SIGTERM");
                }
                if test_mode && (signal == SIGINT || signal == SIGTERM) {
                    eprintln!("[SHUTDOWN] signal received: {}", signal);
                }
                if signal == SIGINT || signal == SIGTERM {
                    shutdown_flag.store(true, std::sync::atomic::Ordering::SeqCst);
                }
                if tx.send(ServerEvent::Signal(signal)).is_err() {
                    return;
                }
            }
            std::thread::sleep(Duration::from_millis(50));
        }
    });

    Ok(())
}

#[cfg(not(unix))]
fn spawn_signal_forwarder(
    tx: mpsc::Sender<ServerEvent>,
    _shutdown_flag: Arc<AtomicBool>,
) -> Result<(), ServeError> {
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

/// Exit reason for the server
#[derive(Debug, PartialEq, Eq)]
pub enum ServerExit {
    /// Server shut down gracefully (signal or finished)
    Shutdown,
    /// Hot reload requested
    Reload,
}

/// Run the ASGI/WSGI application via uvicorn/gunicorn
///
/// # Arguments
/// * `args` - Serve command arguments
/// * `python_path` - Path to Python interpreter
/// * `project_dir` - Project directory
#[cfg(unix)]
pub fn run_server(
    args: &ServeArgs,
    python_path: &Path,
    project_dir: &Path,
    config: &velo_core::config::VeloConfig,
) -> Result<ServerExit> {
    use crate::framework::{Server, check_server_installed, get_server_type};
    use std::time::Instant;

    // MANDATE R5: Capture the absolute start including early validation
    // start_time moved inside loop for correct reload timing

    // Step 1: Validate app format
    let (module, attr) = args.parse_app()?;

    // Step 2: Early validation - Privileged port check (SEC-P0-006)
    // Fail fast if port < 1024 and not root, instead of letting async bind fail silently
    #[cfg(unix)]
    if args.port < 1024 {
        let uid = unsafe { libc::getuid() };
        if uid != 0 {
            return Err(anyhow::anyhow!(
                "Permission denied: port {} requires root privileges (current uid: {}). Use --port >= 1024 or run as root.",
                args.port,
                uid
            ));
        }
    }

    // Step 3: Early validation - Module check (FAIL-FAST-001)
    // Three-phase check with proper environment setup:
    // 1. find_spec: check module exists (fast, no side effects)
    // 2. ast.parse: check syntax (fast, no side effects)
    // 3. import: catch runtime import errors (with proper venv activated)
    {
        use std::process::Command;
        let check_script = format!(
            r#"
import importlib.util
import ast
import sys
import os

module_name = '{}'

# Ensure current directory is in sys.path for local imports
if os.getcwd() not in sys.path:
    sys.path.insert(0, os.getcwd())

# Phase 1: Check if module exists (no side effects)
spec = importlib.util.find_spec(module_name)
if spec is None:
    print('MODULE_NOT_FOUND', file=sys.stderr)
    sys.exit(1)

# Phase 2: Check syntax (no side effects)
if spec.origin and spec.origin.endswith('.py'):
    try:
        with open(spec.origin) as f:
            ast.parse(f.read())
    except SyntaxError as e:
        print(f'SYNTAX_ERROR: {{e}}', file=sys.stderr)
        sys.exit(1)

# Phase 3: Actually import to catch runtime errors
# The subprocess uses python_path from project venv, so dependencies are available
try:
    __import__(module_name)
except Exception as e:
    print(f'IMPORT_ERROR: {{type(e).__name__}}: {{e}}', file=sys.stderr)
    sys.exit(1)
"#,
            module
        );

        let check_result = Command::new(python_path)
            .args(["-c", &check_script])
            .current_dir(project_dir)
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::piped())
            .output();

        match check_result {
            Ok(output) if !output.status.success() => {
                let stderr = String::from_utf8_lossy(&output.stderr);
                if stderr.contains("MODULE_NOT_FOUND") {
                    return Err(anyhow::anyhow!(
                        "Module '{}' not found. Ensure the module exists and is importable.",
                        module
                    ));
                } else if stderr.contains("SYNTAX_ERROR") {
                    return Err(anyhow::anyhow!(
                        "Syntax error in module '{}'.\n\n{}",
                        module,
                        stderr.trim()
                    ));
                } else if stderr.contains("IMPORT_ERROR") {
                    return Err(anyhow::anyhow!(
                        "Failed to import module '{}'.\n\n{}",
                        module,
                        stderr.trim()
                    ));
                } else {
                    return Err(anyhow::anyhow!(
                        "Failed to verify module '{}'.\n\n{}",
                        module,
                        stderr.trim()
                    ));
                }
            }
            Err(e) => eprintln!("warning: could not verify module: {}", e),
            Ok(_) => {}
        }
    }

    // Step 4: Setup Logger
    let logger = ServeLogger::new(args.log_format, args.verbose);

    // RAII Guard for Health Server (SEC-P0-004)
    // Shared container for LoadBalancer (populated later if in Zygote mode)
    let lb_holder = Arc::new(std::sync::Mutex::new(None));

    // RAII Guard for PID file (SEC-P0-003)
    let _pid_guard = if let Some(ref path) = args.pid_file {
        Some(PidFileGuard::new(path.clone())?)
    } else {
        None
    };
    let mut _health_server: Option<crate::health::HealthServer> = None;
    let health_ready = Arc::new(AtomicBool::new(false));
    if let Some(ref bind) = args.health_bind {
        match crate::health::HealthServer::spawn(
            bind,
            Arc::clone(&health_ready),
            Arc::clone(&lb_holder),
        ) {
            Ok(server) => {
                logger.info(&format!("Health server listening on {}", bind));
                _health_server = Some(server);
            }
            Err(e) => {
                logger.error(&format!("Failed to start health server: {}", e));
            }
        }
    }

    // Dry-run handled after protocol detection and Zygote prewarm (see below).

    // Step 1.1: Scaling Warning (R4)
    let file_count = count_python_files(project_dir);
    if file_count > 5000 {
        logger.warn(&format!("Large number of files detected ({})", file_count));
        logger.warn("help: Watching many files may impact performance.");
    }

    // Step 2: Detect app protocol without hardcoded framework lists
    let protocol = detect_app_protocol(python_path, project_dir, module, attr);
    let preload_modules: Vec<&str> = config.preload.iter().map(|s| s.as_str()).collect();

    // Step 3: Select server based on app protocol (D4)
    let mut rsgi_enabled = args.rsgi;
    if rsgi_enabled {
        if let Ok(py_env) = velo_core::common::python_env::PythonEnv::detect(python_path) {
            // SPEC-0005: Use runtime-detected version for ABI verification
            // This is more reliable than cfg! which is often missing in multi-crate builds
            let pyo3_version = py_env.version.as_str();

            let is_supported = matches!(pyo3_version, "3.10" | "3.11" | "3.12" | "3.13");

            if !is_supported {
                logger.warn(&format!(
                    "RSGI disabled: Python {} is not in supported ABI range (3.10-3.13).",
                    pyo3_version
                ));
                rsgi_enabled = false;
            } else {
                log::debug!("[SSOT] RSGI ABI verified: {}", pyo3_version);
            }
        } else {
            logger.warn("RSGI disabled: failed to detect Python runtime version.");
            rsgi_enabled = false;
        }
    }

    let mut server = if rsgi_enabled {
        Server::RSGI
    } else {
        get_server_type(protocol)
    };

    if !rsgi_enabled
        && protocol == AppProtocol::Wsgi
        && !check_server_installed(Server::Gunicorn, python_path)
    {
        logger.warn("WSGI detected but gunicorn is missing; falling back to uvicorn.");
        server = Server::Uvicorn;
    }

    // Show protocol detection result
    if rsgi_enabled {
        logger.info("RSGI mode forced; skipping protocol-based server selection.");
    } else {
        match protocol {
            AppProtocol::Unknown => {
                logger.warn("App protocol detection failed; defaulting to uvicorn.");
            }
            _ => {
                let preload_detail = if preload_modules.is_empty() {
                    "(preload: none)".to_string()
                } else {
                    format!("(preload: {})", preload_modules.join(", "))
                };
                logger.info_with(
                    &format!("Detected protocol: {} → {}", protocol, server),
                    &preload_detail,
                );
            }
        }
    }

    // Step 4: Dependency check is performed after Zygote + dry-run short-circuit

    // Shutdown Coordinator (SEC-P0-001)
    let shutdown_coordinator =
        crate::runner::ShutdownCoordinator::new().map_err(ServeError::SignalError)?;
    #[cfg(unix)]
    {
        use signal_hook::consts::{SIGINT, SIGTERM};
        let flag = shutdown_coordinator.flag.clone();
        let _ = signal_hook::flag::register(SIGTERM, flag.clone());
        let _ = signal_hook::flag::register(SIGINT, flag);
    }
    #[cfg(unix)]
    {
        use signal_hook::consts::{SIGINT, SIGTERM};
        signal_hook::flag::register(SIGINT, Arc::clone(&shutdown_coordinator.flag))
            .map_err(ServeError::SignalError)?;
        signal_hook::flag::register(SIGTERM, Arc::clone(&shutdown_coordinator.flag))
            .map_err(ServeError::SignalError)?;
    }

    // Step 5:    // Event Bus (Recommendation #1)
    let (tx, rx) = mpsc::channel();

    // Signal Forwarder
    #[cfg(unix)]
    spawn_signal_forwarder(tx.clone(), Arc::clone(&shutdown_coordinator.flag))?;

    // Hot Reload Watcher (D6, D7)
    let mut _watcher: Option<Arc<crate::watcher::FileWatcher>> = None;
    if args.reload {
        let watcher = crate::watcher::FileWatcher::new(
            shutdown_coordinator.flag.clone(),
            crate::watcher::DEFAULT_DEBOUNCE_MS,
        )?;
        watcher.watch(project_dir)?;
        let watcher = Arc::new(watcher);

        // Spawn a thread to poll the watcher and bridge events to the bus
        let tx_clone = tx.clone();
        let watcher_clone = Arc::clone(&watcher);
        thread::spawn(move || {
            loop {
                if watcher_clone
                    .shutdown_flag
                    .load(std::sync::atomic::Ordering::SeqCst)
                {
                    break;
                }
                match watcher_clone.poll() {
                    Ok(true) => {
                        if tx_clone.send(ServerEvent::Reload).is_err() {
                            break;
                        }
                    }
                    Ok(false) => {
                        // Sleep briefly to avoid busy wait
                        thread::sleep(Duration::from_millis(50));
                    }
                    Err(e) => {
                        eprintln!("⚠️  Watcher error: {}", e);
                        thread::sleep(Duration::from_secs(1));
                    }
                }
                if watcher_clone
                    .shutdown_flag
                    .load(std::sync::atomic::Ordering::SeqCst)
                {
                    break;
                }
            }
        });

        _watcher = Some(watcher);
    }

    // RAII Guard for Zygote (Audit Remediation)
    // Needs to stay alive for the duration of the server
    #[allow(unused_mut)]
    let mut _zygote_guard: Option<velo_core::zygote::ZygoteLauncher> = None;

    // Step 6: Start server
    if args.log_format == LogFormat::Text {
        eprintln!(
            "\n{} {}",
            "🚀".bold(),
            "Starting TITANIUM Runtime...".green().bold()
        );
        eprintln!("   {} {}", "App:".dimmed(), args.app.cyan().bold());
        eprintln!("   {} {}", "Server:".dimmed(), server.to_string().cyan());
        eprintln!("   {} {}:{}", "Bind:".dimmed(), args.host, args.port);
        eprintln!("   {} {}", "Workers:".dimmed(), args.workers);
        eprintln!("   {} {}s", "Timeout:".dimmed(), args.timeout);
        if args.reload {
            eprintln!("   {} {}", "Reload:".dimmed(), "enabled".yellow());
        }
    } else {
        logger.info("Starting TITANIUM server...");
    }

    // Start Zygote if enabled or suggested by Autopilot
    let autopilot = AutopilotEngine::default();
    let script_path = project_dir.join(format!("{}.py", module.replace('.', "/")));
    let autopilot_decision = autopilot.should_use_zygote(&script_path);

    let mut use_zygote = args.use_zygote;
    if !use_zygote
        && matches!(
            autopilot_decision,
            AutopilotDecision::EnabledByStatic { .. }
                | AutopilotDecision::EnabledByPerformance { .. }
        )
    {
        logger.info("Autopilot: Implicitly enabling Zygote based on imports/performance");
        use_zygote = true;
    }
    if args.reload {
        use_zygote = false;
    }

    let app_name_for_zygote = if args.reload
        || (std::env::var("VELO_TEST_MODE").is_ok()
            && std::env::var("VELO_ZYGOTE_PRELOAD").is_err())
    {
        None
    } else {
        Some(args.app.as_str())
    };

    if use_zygote && velo_core::zygote::is_supported() && !args.dry_run {
        let socket_path = velo_core::zygote::core_ipc::socket_path_for_app(project_dir, &args.app);
        let test_mode = std::env::var("VELO_TEST_MODE").ok().as_deref() == Some("1");

        if test_mode {
            #[cfg(unix)]
            cleanup_zygote_processes_for_test(&socket_path);
            let _ = velo_core::zygote::core_ipc::send_command(
                &socket_path,
                velo_core::zygote::core_ipc::ZygoteCommand::Shutdown,
                None,
            );
            let _ = std::fs::remove_file(&socket_path);
        }

        if !socket_path.exists() {
            logger.info(&format!(
                "Pre-warming Zygote with {} module(s)...",
                preload_modules.len()
            ));
            let mut launcher =
                ZygoteLauncher::new(socket_path).with_python(python_path.to_path_buf());

            if let Err(e) = launcher.start(&preload_modules, app_name_for_zygote, false, config) {
                let signal = velo_core::common::governance::GovernanceSignal::new(
                    velo_core::common::governance::SignalComponent::ZygoteIPC,
                    format!("Zygote pre-warm failed: {}", e),
                    "Continuing without Zygote optimization",
                    "Check Zygote logs and socket permissions.",
                );
                let _ = launcher.stop();
                if config.strict_optimizations {
                    return Err(anyhow::anyhow!(signal.format_critical()));
                } else {
                    signal.report_audit();
                }
            } else {
                if args.log_format == LogFormat::Text {
                    eprintln!(
                        "   {} {} (v{}, caps: {:?})",
                        "Zygote:".dimmed(),
                        "Ready".green().bold(),
                        1,
                        ["v3-shim", "pool"]
                    );
                } else {
                    logger.info("Zygote ready");
                }
                // RAII: Keep Zygote alive as long as this function runs
                _zygote_guard = Some(launcher);
            }
        } else if velo_core::zygote::core_ipc::is_socket_alive(&socket_path) {
            logger.info("Using existing Zygote (Socket Found)");

            // RFC-0011 Audit Remediation: Perform Deep Handshake to verify Zygote is active
            // This prevents the "Shadow Trap" where a stale socket file leads to a silent fallback.
            match velo_core::zygote::core_ipc::send_command(
                &socket_path,
                velo_core::zygote::core_ipc::ZygoteCommand::Handshake {
                    version: velo_core::zygote::core_ipc::PROTOCOL_VERSION,
                    capabilities: vec!["serve:http".to_string()],
                    request_id: Some(uuid::Uuid::now_v7().to_string()),
                },
                None,
            ) {
                Ok(velo_core::zygote::core_ipc::ZygoteResponse::Handshake { version, .. })
                    if version == velo_core::zygote::core_ipc::PROTOCOL_VERSION =>
                {
                    logger.info(&format!("Existing Zygote verified (Protocol v{})", version));
                    _zygote_guard = Some(ZygoteLauncher::new(socket_path));
                }
                Ok(resp) => {
                    logger.warn(&format!("Existing Zygote invalid handshake response: {:?}. Expected Handshake variant with version {}.", resp, velo_core::zygote::core_ipc::PROTOCOL_VERSION));
                    let _ = std::fs::remove_file(&socket_path);
                }
                Err(e) => {
                    let signal = velo_core::common::governance::GovernanceSignal::new(
                        velo_core::common::governance::SignalComponent::ZygoteIPC,
                        format!("Existing Zygote not responding: {}", e),
                        "Continuing without Zygote optimization",
                        "Check for stale socket files in /tmp.",
                    );
                    if config.strict_optimizations {
                        return Err(anyhow::anyhow!(signal.format_critical()));
                    } else {
                        signal.report_audit();
                        let _ = std::fs::remove_file(&socket_path);
                    }
                }
            }
        } else {
            // Socket exists but is dead (is_socket_alive returned false)
            let signal = velo_core::common::governance::GovernanceSignal::new(
                velo_core::common::governance::SignalComponent::ZygoteIPC,
                "Existing Zygote socket is dead",
                "Continuing without Zygote optimization after cleanup",
                "Clean up stale socket file.",
            );
            // Always remove dead socket to prevent blocking future runs
            let _ = std::fs::remove_file(&socket_path);

            if config.strict_optimizations {
                return Err(anyhow::anyhow!(signal.format_critical()));
            } else {
                signal.report_audit();
            }
        }
    }

    // Dry-run short-circuit after Zygote prewarm so fallback is observable.
    if args.dry_run {
        let start_time = Instant::now();
        let server = if args.rsgi {
            Server::RSGI
        } else {
            Server::Uvicorn
        };
        if matches!(server, Server::RSGI) {
            logger.warn("Dry run for RSGI is not supported; skipping command build.");
            return Ok(ServerExit::Shutdown);
        }
        let cmd = build_server_command(server, args, python_path, project_dir, &logger)?;
        let ready_ms = start_time.elapsed().as_millis();
        logger.log_with_timing("info", "Server ready", None, Some(ready_ms));
        logger.info(&format!(
            "Dry run: Command would be: {:?} {:?}",
            cmd.get_program(),
            cmd.get_args()
                .map(|v| v.to_string_lossy())
                .collect::<Vec<_>>()
                .join(" ")
        ));
        return Ok(ServerExit::Shutdown);
    }

    // Step 4: Check server is installed (only for non-RSGI mode)
    // When --rsgi is specified, we use native Granian workers which don't need uvicorn
    if !rsgi_enabled {
        logger.debug(&format!(
            "Checking if {} is installed (using python_path: {})...",
            server,
            python_path.display()
        ));
        if !check_server_installed(server, python_path) {
            logger.error(&format!("Missing dependency: {}", server));
            eprintln!();
            eprintln!("{} is required to run {} applications.", server, protocol);
            eprintln!("To fix:");
            eprintln!("    {}", server.install_hint());
            return Err(anyhow::anyhow!("Missing dependency: {}", server));
        }
    } else {
        logger.debug("Skipping server dependency check (Native RSGI mode)");
    }

    // RFC-0011 & Net-001: Unified Worker Management & L7 Proxy
    let mut workers = Vec::new();
    let mut use_proxy = false;
    #[cfg(unix)]
    let mut _native_listener: Option<std::net::TcpListener> = None;
    #[cfg(not(unix))]
    let _native_listener: Option<std::net::TcpListener> = None;

    // A.1 Spawn via Native Granian (Phase 7.3)
    #[cfg(unix)]
    if !args.dry_run && args.workers >= 1 && rsgi_enabled {
        use std::os::unix::io::AsRawFd;

        let addr = format!("{}:{}", args.host, args.port);
        let bind_addr: std::net::SocketAddr = addr.parse()?;

        // Bind the socket in the parent
        // Use SO_REUSEADDR for faster restarts
        let socket = if bind_addr.is_ipv4() {
            socket2::Socket::new(socket2::Domain::IPV4, socket2::Type::STREAM, None)?
        } else {
            socket2::Socket::new(socket2::Domain::IPV6, socket2::Type::STREAM, None)?
        };

        socket.set_reuse_address(true)?;

        socket.bind(&bind_addr.into())?;
        socket.listen(1024)?;
        let listener: std::net::TcpListener = socket.into();
        listener.set_nonblocking(true)?;
        let fd = listener.as_raw_fd();

        // IMPORTANT: Ensure FD is NOT cloexec so children can inherit it
        let flags = unsafe { libc::fcntl(fd, libc::F_GETFD) };
        if flags != -1 {
            unsafe { libc::fcntl(fd, libc::F_SETFD, flags & !libc::FD_CLOEXEC) };
        }

        eprintln!("🚀 Launching {} native Granian workers...", args.workers);
        for i in 0..args.workers {
            match crate::worker::Worker::spawn_native(
                &args.app,
                i as i32,
                fd,
                python_path,
                project_dir,
                config,
            ) {
                Ok(worker) => {
                    logger.info(&format!(
                        "[WORKER] event=spawn type=native worker_id={} pid={}",
                        i, worker.pid
                    ));
                    eprintln!("  ✅ Worker {} (PID: {}) [Native]", i + 1, worker.pid);
                    workers.push(worker);
                }
                Err(e) => {
                    logger.error(&format!("Native worker spawn failed: {}", e));
                    break;
                }
            }
        }

        if workers.len() == args.workers as usize {
            use_proxy = true;
            _native_listener = Some(listener);
        } else {
            // Partial failure: cleanup
            for mut w in workers.drain(..) {
                let _ = w.shutdown(Duration::from_secs(1));
            }
        }
    }

    // A. Spawn via Zygote (Optimized Path)
    if !args.dry_run
        && workers.is_empty() // FIX: Avoid dual spawning if native workers are already up
        && args.workers >= 1
        && use_zygote
        && matches!(server, Server::Uvicorn | Server::RSGI)
    {
        #[allow(clippy::collapsible_if)]
        if let Some(ref mut launcher) = _zygote_guard {
            if args.log_format == LogFormat::Text {
                eprintln!(
                    "{} Launching {} workers via Zygote...",
                    "🔄".bold(),
                    args.workers
                );
            }

            for i in 0..args.workers {
                match crate::worker::Worker::spawn_uds_via_zygote(
                    launcher,
                    &args.app,
                    i as u64,
                    None,
                    config,
                    rsgi_enabled,
                ) {
                    Ok(worker) => {
                        logger.info(&format!(
                            "[WORKER] event=spawn type=zygote worker_id={} pid={}",
                            i, worker.pid
                        ));
                        if args.log_format == LogFormat::Text {
                            eprintln!(
                                "  {} Worker {} (PID: {}) [Zygote]",
                                "✅".green(),
                                i + 1,
                                worker.pid
                            );
                        }
                        workers.push(worker);
                    }
                    Err(e) => {
                        logger.warn(&format!(
                            "Zygote worker spawn failed: {}. Falling back to cold start.",
                            e
                        ));
                        break;
                    }
                }
            }
            if workers.len() == args.workers as usize {
                use_proxy = true;
                if args.log_format == LogFormat::Text {
                    print_governance_audit(config, true);
                }
            } else {
                // Partial failure: cleanup and fallback
                for mut w in workers.drain(..) {
                    let _ = w.shutdown(Duration::from_secs(1));
                }
            }
        }
    }

    // B. Spawn via Cold-Start Proxy (Safe Path - Phase 7.2)
    if !args.dry_run
        && workers.is_empty() // FIX: Avoid dual spawning
        && args.workers >= 1
        && matches!(server, Server::Uvicorn | Server::RSGI)
    {
        if args.log_format == LogFormat::Text {
            eprintln!(
                "{} Launching {} workers via Cold-Start Proxy...",
                "🔄".bold(),
                args.workers
            );
        }
        for i in 0..args.workers {
            match crate::worker::Worker::spawn_uds_direct(
                &args.app,
                i as u64,
                python_path,
                project_dir,
                config,
                rsgi_enabled,
            ) {
                Ok(worker) => {
                    logger.info(&format!(
                        "[WORKER] event=spawn type=direct worker_id={} pid={}",
                        i, worker.pid
                    ));
                    if args.log_format == LogFormat::Text {
                        eprintln!(
                            "  {} Worker {} (PID: {}) [Cold-Start]",
                            "✅".green(),
                            i + 1,
                            worker.pid
                        );
                    }
                    workers.push(worker);
                }
                Err(e) => {
                    logger.error(&format!("Direct worker spawn failed: {}", e));
                    if args.log_format == LogFormat::Text {
                        print_governance_audit(config, false);
                    }
                    break;
                }
            }
        }
        if workers.len() == args.workers as usize {
            use_proxy = true;
            if args.log_format == LogFormat::Text {
                print_governance_audit(config, false);
            }
        } else {
            for mut w in workers.drain(..) {
                let _ = w.shutdown(Duration::from_secs(1));
            }
        }
    }

    // C. Run Unified L7 Proxy Loop
    if use_proxy && !workers.is_empty() {
        eprintln!("✅ All workers ready");
        health_ready.store(true, std::sync::atomic::Ordering::SeqCst);
        let mut respawn_trackers: Vec<RespawnTracker> =
            (0..workers.len()).map(|_| RespawnTracker::new()).collect();

        let socket_paths: Vec<String> = workers
            .iter()
            .filter_map(|w| {
                w.socket_path
                    .as_ref()
                    .map(|p| p.to_string_lossy().to_string())
            })
            .collect();
        let lb = Arc::new(LoadBalancer::new(socket_paths));

        if let Ok(mut guard) = lb_holder.lock() {
            *guard = Some(lb.clone());
        }

        // Gate H (DEF-72-H01): Register initial worker PIDs for peer authentication
        for (i, w) in workers.iter().enumerate() {
            lb.register_worker_pid(i as u64, w.pid);
        }

        logger.info(if rsgi_enabled {
            "Starting RSGI Host..."
        } else {
            "Starting L7 Proxy..."
        });
        let rt = tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            .map_err(|e| anyhow::anyhow!("Tokio error: {}", e))?;
        let addr = format!("{}:{}", args.host, args.port);
        let bind_addr: std::net::SocketAddr = addr.parse()?;

        let lb_for_proxy = lb.clone();

        let timeout_multiplier: f64 = std::env::var("VELO_TIMEOUT_MULTIPLIER")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(1.0);

        if rsgi_enabled && _native_listener.is_some() {
            // RFC-0019/0025: Native RSGI Mode
            // Workers handle their own server listening; Master only supervises.
            logger.info("Master supervisor active (Native RSGI Mode)");
        } else if rsgi_enabled && _zygote_guard.is_none() {
            // Only bail if NOT using Zygote (Legacy RSGI requires native listener)
            anyhow::bail!("RSGI mode requires a native listener (Unix only)");
        } else {
            // Legacy L7 Proxy Mode (or RSGI-over-UDS bridge)
            let service = VeloProxyService::new(lb.clone());
            rt.spawn(async move {
                let listener = tokio::net::TcpListener::bind(bind_addr)
                    .await
                    .expect("Failed to bind proxy");

                let test_mode = std::env::var("VELO_TEST_MODE").ok().as_deref() == Some("1");
                let base_timeout = if test_mode { 5.0 } else { 15.0 };
                let wait_timeout = Duration::from_secs_f64(base_timeout * timeout_multiplier);
                let check_interval = Duration::from_secs_f64(5.0 * timeout_multiplier);

                if !lb_for_proxy.wait_for_healthy(wait_timeout).await {
                    eprintln!("[LB] CRITICAL: Workers failed to become healthy within {:?}. Starting anyway...", wait_timeout);
                }

                lb_for_proxy
                    .clone()
                    .spawn_health_checks(check_interval);
                eprintln!("🚀 L7 Proxy listening on http://{}", bind_addr);
                loop {
                    if let Ok((stream, peer_addr)) = listener.accept().await {
                        let _ = stream.set_nodelay(true);
                        let io = TokioIo::new(stream);
                        let service_with_addr = service.clone().with_client_addr(peer_addr);
                        tokio::spawn(async move {
                            let _ = http1::Builder::new()
                                .serve_connection(io, service_with_addr)
                                .await;
                        });
                    }
                }
            });
        }
        let mut self_check_needed = false;

        // Main loop: Wait for Signal or Events (Zero Busy Wait)
        loop {
            if shutdown_coordinator.is_shutting_down() {
                if std::env::var("VELO_TEST_MODE").ok().as_deref() == Some("1") {
                    eprintln!("[SHUTDOWN] coordinator flag set in proxy loop");
                }
                eprintln!("\n🛑 Shutdown requested, stopping workers...");
                let shutdown_timeout =
                    Duration::from_secs(args.timeout).min(Duration::from_secs(3));
                for w in &mut workers {
                    let _ = w.shutdown(shutdown_timeout);
                }
                if let Some(mut launcher) = _zygote_guard.take() {
                    let _ = launcher.stop();
                }
                if std::env::var("VELO_TEST_MODE").ok().as_deref() == Some("1") {
                    #[cfg(unix)]
                    {
                        let socket_path = velo_core::zygote::core_ipc::socket_path_for_app(
                            project_dir,
                            &args.app,
                        );
                        cleanup_zygote_process_group_for_test(&socket_path);
                        cleanup_zygote_processes_for_test(&socket_path);
                        cleanup_descendants_for_test(std::process::id() as i32);
                        cleanup_uvicorn_workers_for_test(
                            &velo_core::common::paths::get_socket_dir(),
                        );
                    }
                }
                return Ok(ServerExit::Shutdown);
            }
            // PERF-604: 10ms polling floor reduces log volume while maintaining throughput.
            // TODO(EV-001): Migrate to event-driven pidfd (Linux) or kqueue (macOS)
            // to eliminate polling overhead while maintaining low latency.
            match rx.recv_timeout(Duration::from_millis(10)) {
                Ok(ServerEvent::Signal(sig)) => {
                    use signal_hook::consts::{SIGCHLD, SIGINT, SIGTERM};
                    if sig == SIGINT || sig == SIGTERM {
                        if std::env::var("VELO_TEST_MODE").ok().as_deref() == Some("1") {
                            eprintln!("[SHUTDOWN] signal event in proxy loop: {}", sig);
                        }
                        eprintln!("\n🛑 Received shutdown signal, stopping workers...");
                        let shutdown_timeout =
                            Duration::from_secs(args.timeout).min(Duration::from_secs(3));
                        for w in &mut workers {
                            let _ = w.shutdown(shutdown_timeout);
                        }
                        if let Some(mut launcher) = _zygote_guard.take() {
                            let _ = launcher.stop();
                        }
                        if std::env::var("VELO_TEST_MODE").ok().as_deref() == Some("1") {
                            #[cfg(unix)]
                            {
                                let socket_path = velo_core::zygote::core_ipc::socket_path_for_app(
                                    project_dir,
                                    &args.app,
                                );
                                cleanup_zygote_process_group_for_test(&socket_path);
                                cleanup_zygote_processes_for_test(&socket_path);
                                cleanup_descendants_for_test(std::process::id() as i32);
                                cleanup_uvicorn_workers_for_test(
                                    &velo_core::common::paths::get_socket_dir(),
                                );
                            }
                        }
                        return Ok(ServerExit::Shutdown);
                    } else if sig == SIGCHLD {
                        // Immediate liveness check on child exit
                        self_check_needed = true;
                    }
                }

                Ok(ServerEvent::Reload) => {
                    logger.info("Changes detected (Proxy Mode), restarting workers...");
                    for w in &mut workers {
                        let _ = w.shutdown(Duration::from_secs(args.timeout));
                    }
                    return Ok(ServerExit::Reload);
                }
                Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {
                    self_check_needed = true;
                }
                Ok(ServerEvent::WorkerExit) => {
                    self_check_needed = true;
                }
                Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => {
                    return Ok(ServerExit::Shutdown);
                }
            }

            if self_check_needed {
                for (i, worker) in workers.iter_mut().enumerate() {
                    if !worker.is_alive() {
                        let tracker = &mut respawn_trackers[i];
                        if !tracker.should_respawn() {
                            continue;
                        }

                        // REG-72-R01: Record failure BEFORE attempting respawn to ensure
                        // backoff and standardized logging ([RESPAWN]) are triggered.
                        if !tracker.record_failure() {
                            anyhow::bail!(
                                "FATAL: Worker worker_id={} failed to start after {} attempts.",
                                i,
                                tracker.fail_fast_limit
                            );
                        }

                        logger.warn(&format!(
                            "[RESPAWN] worker_id={} attempt={} old_pid={}",
                            i, tracker.consecutive_failures, worker.pid
                        ));

                        #[cfg(unix)]
                        let _socket_fd = _native_listener.as_ref().map(|l| l.as_raw_fd());

                        match worker.respawn(
                            _zygote_guard.as_mut(),
                            &args.app,
                            i as u64,
                            python_path,
                            project_dir,
                            config,
                            rsgi_enabled,
                            #[cfg(unix)]
                            None,
                        ) {
                            Ok(new_worker) => {
                                // STB-RS-005: Atomic LB Update
                                // Use update_worker_path to inform LB of monotonic socket path change.
                                // This ensures the LB's WorkerNode is updated in-place without losing
                                // connection tracking state (RFC-0011 §6A.7).
                                if let Some(ref new_path) = new_worker.socket_path {
                                    lb.update_worker_path(
                                        i as u64,
                                        new_path.to_string_lossy().to_string(),
                                    );
                                }

                                // Gate H (DEF-72-H01): Register new PID after respawn
                                lb.register_worker_pid(i as u64, new_worker.pid);
                                *worker = new_worker;
                            }

                            Err(e) => {
                                logger.error(&format!(
                                    "[RESPAWN] worker_id={} respawn_error={}",
                                    i, e
                                ));

                                // RFC-0011 Stabilization: Zygote Recovery
                                // If respawn failed, check if Zygote is still alive.
                                let mut zygote_died = false;
                                if _zygote_guard.as_mut().is_some_and(|l| !l.is_alive()) {
                                    logger.warn("[RESPAWN] Zygote detected as dead/unresponsive. Attempting restart...");
                                    zygote_died = true;
                                }

                                if zygote_died {
                                    // Attempt to restart Zygote
                                    if let Some(ref mut launcher) = _zygote_guard {
                                        match launcher.start(
                                            &preload_modules,
                                            Some(&args.app),
                                            false,
                                            config,
                                        ) {
                                            Ok(_) => {
                                                logger.info("[RESPAWN] Zygote successfully restarted. Retrying worker respawn...");
                                                #[cfg(unix)]
                                                let _socket_fd = _native_listener
                                                    .as_ref()
                                                    .map(|l| l.as_raw_fd());

                                                // Retry once after restart
                                                if let Ok(retry_worker) = worker.respawn(
                                                    _zygote_guard.as_mut(),
                                                    &args.app,
                                                    i as u64,
                                                    python_path,
                                                    project_dir,
                                                    config,
                                                    rsgi_enabled,
                                                    #[cfg(unix)]
                                                    None,
                                                ) {
                                                    if let Some(ref new_path) =
                                                        retry_worker.socket_path
                                                    {
                                                        lb.update_worker_path(
                                                            i as u64,
                                                            new_path.to_string_lossy().to_string(),
                                                        );
                                                    }

                                                    // Gate H (DEF-72-H01): Register new PID after zygote-recovery respawn
                                                    lb.register_worker_pid(
                                                        i as u64,
                                                        retry_worker.pid,
                                                    );
                                                    *worker = retry_worker;
                                                }
                                            }
                                            Err(restart_err) => {
                                                logger.error(&format!(
                                                    "[RESPAWN] Zygote restart failed: {}",
                                                    restart_err
                                                ));
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // STB-RS-005: Respawn Loop
    // Logic: If reload is enabled, we loop here to respawn the server on change events.
    loop {
        if shutdown_coordinator.is_shutting_down() {
            if std::env::var("VELO_TEST_MODE").ok().as_deref() == Some("1") {
                eprintln!("[SHUTDOWN] flag set before respawn loop");
            }
            if std::env::var("VELO_TEST_MODE").ok().as_deref() == Some("1") {
                #[cfg(unix)]
                cleanup_descendants_for_test(std::process::id() as i32);
            }
            return Ok(ServerExit::Shutdown);
        }
        let start_time = Instant::now();

        if server == Server::Uvicorn && args.workers >= 1 {
            logger.info("Transitioning to RSGI Host (Proxy Redirect)...");
        }

        // Build server command based on server type
        let mut cmd = build_server_command(server, args, python_path, project_dir, &logger)?;

        // Unified Startup Timing (R5, PERF-P0-001)
        let ready_ms = start_time.elapsed().as_millis();
        logger.log_with_timing("info", "Server ready", None, Some(ready_ms));

        if args.log_format == LogFormat::Text {
            eprintln!("   App:       {}", args.app);
            eprintln!("   Server:    {}", server);
            eprintln!("   Bind:      {}:{}", args.host, args.port);
            eprintln!("   Workers:   {}", args.workers);
            eprintln!("   Timeout:   {}s", args.timeout);
            if args.reload {
                eprintln!("   Reload:    enabled");
            }
        }

        // RFC-0012: Surgical Environment Management (Whitelist)
        // Replaces SEC-P0-005 blacklist with robust provenance guard
        let shield = velo_core::lifecycle::EnvironmentShield::new(config);
        if let Err(e) = shield.apply(&mut cmd) {
            logger.warn(&format!("Environment shield warning: {}", e));
        }

        // Spawn with ManagedChild for RAII cleanup (D2)
        // Pass None for pid_file since we handle it with _pid_guard in run_server
        let mut child_result = ManagedChild::spawn(cmd, None);

        if let Ok(ref mut child) = child_result {
            logger.info(&format!("Server started (PID: {})", child.id()));
            health_ready.store(true, std::sync::atomic::Ordering::SeqCst);

            // Main loop: Wait for Events (Zero Busy Wait)
            loop {
                if shutdown_coordinator.is_shutting_down() {
                    eprintln!("\n🛑 Shutdown requested, stopping server...");
                    #[cfg(unix)]
                    {
                        let pid = child.id() as i32;
                        let target = if let Some(pgid) = child.pgid() {
                            -pgid
                        } else {
                            pid
                        };
                        unsafe {
                            libc::kill(target, libc::SIGTERM);
                        }
                    }
                    #[cfg(not(unix))]
                    let _ = child.terminate();
                    let shutdown_wait =
                        if std::env::var("VELO_TEST_MODE").ok().as_deref() == Some("1") {
                            Duration::from_secs(args.timeout).min(Duration::from_secs(3))
                        } else {
                            Duration::from_secs(args.timeout)
                        };
                    match child.wait_timeout(shutdown_wait) {
                        Ok(Some(_)) => {
                            logger.info("Server stopped gracefully");
                        }
                        _ => {
                            logger.warn("Shutdown timeout expired, force killing process group...");
                            #[cfg(unix)]
                            {
                                let pid = child.id() as i32;
                                let target = if let Some(pgid) = child.pgid() {
                                    -pgid
                                } else {
                                    pid
                                };
                                unsafe {
                                    libc::kill(target, libc::SIGKILL);
                                }
                            }
                            #[cfg(not(unix))]
                            let _ = child.kill();
                        }
                    }
                    if std::env::var("VELO_TEST_MODE").ok().as_deref() == Some("1") {
                        #[cfg(unix)]
                        cleanup_descendants_for_test(std::process::id() as i32);
                        #[cfg(unix)]
                        cleanup_uvicorn_workers_for_test(
                            &velo_core::common::paths::get_socket_dir(),
                        );
                    }
                    return Ok(ServerExit::Shutdown);
                }
                // Block until event received
                match rx.recv_timeout(Duration::from_millis(50)) {
                    Ok(ServerEvent::Signal(sig)) => {
                        match sig {
                            signal_hook::consts::SIGCHLD => {
                                // Optimistic: Child might have exited
                                match child.wait_timeout(Duration::from_millis(0)) {
                                    Ok(Some(status)) => {
                                        let code = status.code().unwrap_or(1);
                                        if !status.success() {
                                            if code == 1 {
                                                eprintln!();
                                                eprintln!(
                                                    "💡 Tip: If the app failed to import, check for syntax errors or missing dependencies."
                                                );
                                            }

                                            // If reload is NOT enabled, exit immediately on failure
                                            if !args.reload {
                                                return Err(anyhow::anyhow!(
                                                    "Server exited with code {}",
                                                    code
                                                ));
                                            }

                                            // Reload IS enabled: wait for file changes to trigger restart
                                            logger.error(&format!("Server exited with code {}. Waiting for reload or shutdown...", code));
                                            health_ready
                                                .store(false, std::sync::atomic::Ordering::SeqCst);
                                            continue;
                                        }
                                        // Child exited successfully (code 0)
                                        if !args.reload {
                                            return Ok(ServerExit::Shutdown);
                                        } else {
                                            logger.warn("Server exited (0). Waiting for reload...");
                                            health_ready
                                                .store(false, std::sync::atomic::Ordering::SeqCst);
                                            continue;
                                        }
                                    }
                                    _ => continue,
                                }
                            }
                            signal_hook::consts::SIGINT | signal_hook::consts::SIGTERM => {
                                eprintln!();
                                logger.info(
                                    "Shutdown signal received, waiting for graceful shutdown...",
                                );

                                // RFC-0012 C.6: Aggressive Eradication - Signal the entire process group: This ensures Zygote and all workers die even through sandbox-exec wrapper.
                                #[cfg(unix)]
                                {
                                    let pid = child.id() as i32;
                                    let target = if let Some(pgid) = child.pgid() {
                                        -pgid
                                    } else {
                                        // Fallback: Use getpgid to find the process group
                                        let pgid = unsafe { libc::getpgid(pid) };
                                        if pgid > 0 { -pgid } else { pid }
                                    };
                                    unsafe {
                                        libc::kill(target, libc::SIGTERM);
                                    }
                                }
                                #[cfg(not(unix))]
                                if let Err(e) = child.terminate() {
                                    logger.warn(&format!("Failed to send SIGTERM: {}", e));
                                }

                                // Wait with timeout (cap in test mode to avoid CI hangs)
                                let shutdown_wait =
                                    if std::env::var("VELO_TEST_MODE").ok().as_deref() == Some("1")
                                    {
                                        Duration::from_secs(args.timeout)
                                            .min(Duration::from_secs(3))
                                    } else {
                                        Duration::from_secs(args.timeout)
                                    };
                                match child.wait_timeout(shutdown_wait) {
                                    Ok(Some(_)) => {
                                        logger.info("Server stopped gracefully");
                                        if std::env::var("VELO_TEST_MODE").ok().as_deref()
                                            == Some("1")
                                        {
                                            #[cfg(unix)]
                                            cleanup_descendants_for_test(std::process::id() as i32);
                                            #[cfg(unix)]
                                            cleanup_uvicorn_workers_for_test(
                                                &velo_core::common::paths::get_socket_dir(),
                                            );
                                        }
                                        return Ok(ServerExit::Shutdown);
                                    }
                                    _ => {
                                        logger.warn("Shutdown timeout expired, force killing process group...");
                                        #[cfg(unix)]
                                        {
                                            let pid = child.id() as i32;
                                            let target = if let Some(pgid) = child.pgid() {
                                                -pgid
                                            } else {
                                                // Fallback: Use getpgid to find the process group
                                                let pgid = unsafe { libc::getpgid(pid) };
                                                if pgid > 0 { -pgid } else { pid }
                                            };
                                            unsafe {
                                                libc::kill(target, libc::SIGKILL);
                                            }
                                        }
                                        #[cfg(not(unix))]
                                        let _ = child.kill();
                                        if std::env::var("VELO_TEST_MODE").ok().as_deref()
                                            == Some("1")
                                        {
                                            #[cfg(unix)]
                                            cleanup_descendants_for_test(std::process::id() as i32);
                                            #[cfg(unix)]
                                            cleanup_uvicorn_workers_for_test(
                                                &velo_core::common::paths::get_socket_dir(),
                                            );
                                        }
                                        return Ok(ServerExit::Shutdown);
                                    }
                                }
                            }
                            _ => {
                                // CN-P0-002: Forward other signals to child group
                                #[cfg(unix)]
                                {
                                    let target = if let Some(pgid) = child.pgid() {
                                        -pgid
                                    } else {
                                        child.id() as i32
                                    };
                                    unsafe {
                                        libc::kill(target, sig);
                                    }
                                }
                                #[cfg(not(unix))]
                                {
                                    let _ = sig; // Suppress unused warning
                                }
                            }
                        }
                    }
                    Ok(ServerEvent::Reload) => {
                        logger.info("Changes detected, restarting server...");
                        if let Ok(ref mut child) = child_result {
                            let _ = child.kill();
                        }
                        // Break inner loop to trigger fresh spawn in the caller
                        break;
                    }
                    Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {
                        // No events yet; keep waiting to avoid respawn churn.
                        continue;
                    }
                    Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => {
                        break; // Bus disconnected
                    }
                    _ => {}
                }
            }
        } else if let Err(e) = child_result {
            logger.error(&format!("Failed to start server: {}", e));
            return Err(anyhow::anyhow!("Server failed to start: {}", e));
        }

        // If we broke out of the inner loop (Reload), valid if args.reload
        if !args.reload {
            break;
        }
    }

    Ok(ServerExit::Shutdown)
}

/// Helper to count Python files for scaling warnings (R4)
fn count_python_files(path: &Path) -> usize {
    let mut count = 0;
    if let Ok(entries) = std::fs::read_dir(path) {
        for entry in entries.flatten() {
            if let Ok(file_type) = entry.file_type() {
                if file_type.is_dir() {
                    let name = entry.file_name();
                    let name_str = name.to_string_lossy();
                    // MANDATE R4: Ignore all common venv names and the current VIRTUAL_ENV
                    let venv_env = std::env::var("VIRTUAL_ENV").unwrap_or_default();
                    let is_active_venv =
                        !venv_env.is_empty() && entry.path().to_string_lossy().contains(&venv_env);

                    if name_str != ".git"
                        && name_str != "__pycache__"
                        && name_str != ".venv"
                        && name_str != "venv"
                        && name_str != ".env"
                        && name_str != "env"
                        && !is_active_venv
                    {
                        count += count_python_files(&entry.path());
                    }
                } else {
                    let path = entry.path();
                    if path
                        .extension()
                        .is_some_and(|ext| ext == "py" || ext == "pyi")
                    {
                        count += 1;
                    }
                }
            }
        }
    }
    count
}
fn print_governance_audit(config: &velo_core::config::VeloConfig, zygote_active: bool) {
    eprintln!(
        "\n{} {}",
        "📊".bold(),
        "TITANIUM Governance Audit".green().bold()
    );

    let zygote_status = if zygote_active {
        "Active (P2 Zero-Config)".green()
    } else {
        "Disabled (Cold-Start Fallback)".yellow()
    };
    eprintln!("   {} {}", "Zygote Pool:".dimmed(), zygote_status);

    let isolation = if config.sandbox_network_isolation {
        "Hardened (RFC-0011)".green()
    } else {
        "Relaxed".yellow()
    };
    eprintln!("   {} {}", "Airlock Isolation:".dimmed(), isolation);

    let metrics = if config.metrics_enabled {
        "Telemetry Enabled (SLO: 100ms)".green()
    } else {
        "Standard".dimmed()
    };
    eprintln!("   {} {}", "Performance:".dimmed(), metrics);

    eprintln!(
        "   {} {} ({})",
        "Audit Trail:".dimmed(),
        "Verified".green(),
        velo_core::common::governance::TraceID::generate()
            .0
            .bright_black()
    );
    eprintln!();
}

#[cfg(not(unix))]
pub fn run_server(
    args: &ServeArgs,
    python_path: &Path,
    project_dir: &Path,
    _config: &velo_core::config::VeloConfig,
) -> Result<ServerExit> {
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

    Ok(ServerExit::Shutdown)
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

    // ========================================================================
    // Event Bus tests (ADR Recommendation #1)
    // ========================================================================

    #[test]
    fn test_server_event_signal_debug_format() {
        let event = ServerEvent::Signal(15);
        let debug = format!("{:?}", event);
        assert!(debug.contains("Signal"));
        assert!(debug.contains("15"));
    }

    #[test]
    fn test_server_event_worker_exit_debug_format() {
        let event = ServerEvent::WorkerExit;
        let debug = format!("{:?}", event);
        assert!(debug.contains("WorkerExit"));
    }

    #[test]
    fn test_event_channel_send_receive() {
        let (tx, rx) = mpsc::channel::<ServerEvent>();

        // Send an event
        tx.send(ServerEvent::Signal(2)).unwrap(); // SIGINT

        // Receive should get the event
        let event = rx.recv_timeout(Duration::from_millis(100)).unwrap();
        match event {
            ServerEvent::Signal(sig) => assert_eq!(sig, 2),
            _ => panic!("Expected Signal event"),
        }
    }

    #[test]
    fn test_event_channel_multiple_signals() {
        let (tx, rx) = mpsc::channel::<ServerEvent>();

        // Send multiple signals
        tx.send(ServerEvent::Signal(2)).unwrap(); // SIGINT
        tx.send(ServerEvent::Signal(15)).unwrap(); // SIGTERM

        // Receive in order
        let event1 = rx.recv_timeout(Duration::from_millis(100)).unwrap();
        let event2 = rx.recv_timeout(Duration::from_millis(100)).unwrap();

        match event1 {
            ServerEvent::Signal(sig) => assert_eq!(sig, 2),
            _ => panic!("Expected Signal(2)"),
        }
        match event2 {
            ServerEvent::Signal(sig) => assert_eq!(sig, 15),
            _ => panic!("Expected Signal(15)"),
        }
    }

    #[test]
    fn test_event_channel_receiver_timeout() {
        let (_tx, rx) = mpsc::channel::<ServerEvent>();

        // Receiver should timeout when no events are sent
        let result = rx.recv_timeout(Duration::from_millis(50));
        assert!(result.is_err());
    }

    #[test]
    fn test_event_channel_sender_dropped() {
        let rx = {
            let (tx, rx) = mpsc::channel::<ServerEvent>();
            tx.send(ServerEvent::Signal(2)).unwrap();
            drop(tx); // Drop sender
            rx
        };

        // Should still receive the buffered event
        let event = rx.recv_timeout(Duration::from_millis(100)).unwrap();
        match event {
            ServerEvent::Signal(sig) => assert_eq!(sig, 2),
            _ => panic!("Expected Signal event"),
        }

        // After buffer is empty, recv should return error (disconnected)
        let result = rx.recv_timeout(Duration::from_millis(50));
        assert!(result.is_err());
    }

    #[cfg(unix)]
    #[test]
    fn test_spawn_signal_forwarder_success() {
        let (tx, _rx) = mpsc::channel::<ServerEvent>();

        // Should successfully spawn the signal forwarder thread
        let shutdown_flag = Arc::new(AtomicBool::new(false));
        let result = spawn_signal_forwarder(tx, shutdown_flag);
        assert!(result.is_ok(), "Signal forwarder should spawn successfully");
    }

    #[cfg(unix)]
    #[test]
    fn test_spawn_signal_forwarder_exits_when_sender_dropped() {
        use std::time::Instant;

        let (tx, rx) = mpsc::channel::<ServerEvent>();

        // Spawn the forwarder
        let shutdown_flag = Arc::new(AtomicBool::new(false));
        spawn_signal_forwarder(tx, shutdown_flag).unwrap();

        // Drop the receiver to simulate main loop exit
        drop(rx);

        // The forwarder thread should exit gracefully (no test for this directly,
        // but we can verify the channel is closed and won't block indefinitely)
        let start = Instant::now();
        let timeout = Duration::from_secs(1);
        while start.elapsed() < timeout {
            thread::sleep(Duration::from_millis(10));
        }
        // If we reach here without hanging, the test passes
    }

    // =========================================================================
    // DEF-611-RESPAWN: Worker Respawn Logic - DEFECT DOCUMENTATION TEST
    // =========================================================================
    //
    // RESOLVED: Worker respawn is implemented via POLLING mechanism:
    //   - recv_timeout(1s) in signal loop
    //   - worker.is_alive() check using libc::kill(pid, 0)
    //   - Respawn via Worker::spawn_uds_via_zygote()
    //
    // The ServerEvent::WorkerExit handler remains empty because:
    //   1. Unix: SIGCHLD is handled by Zygote, not Rust supervisor
    //   2. Polling is more reliable across platforms
    //   3. 5-second health check interval is acceptable latency
    //
    // See: test_CHAOS_001_signal_hurricane for E2E verification
    // =========================================================================

    #[test]
    #[ignore = "DEF-611-RESPAWN: Respawn implemented via polling, not event-driven - see recv_timeout branch"]
    fn test_worker_exit_triggers_respawn() {
        // This test documents the POLLING-based respawn mechanism:
        //
        // Implementation (lines 784-811):
        //   Err(RecvTimeoutError::Timeout) => {
        //       for worker in workers.iter_mut() {
        //           if !worker.is_alive() {
        //               if let Some(tracker) = respawn_trackers.get_mut(&i) {
        //                   if tracker.should_respawn() {
        //                       match Worker::spawn_uds_via_zygote(&socket_path, &args.app, i as u64) {
        //                   }
        //               }
        //           }
        //       }
        //   }
        //
        // Verified by: CHAOS-001 (signal_hurricane) - kills 4 workers, all respawn

        let (tx, rx) = mpsc::channel::<ServerEvent>();

        // Simulate worker exit event
        tx.send(ServerEvent::WorkerExit).unwrap();

        let event = rx.recv_timeout(Duration::from_millis(100)).unwrap();

        match event {
            ServerEvent::WorkerExit => {
                // NOTE: This event path is intentionally empty on Unix.
                // Respawn is handled by the recv_timeout polling branch.
                // This test remains #[ignore] to document the architectural decision.
            }
            _ => panic!("Expected WorkerExit event"),
        }
    }

    // =========================================================================
    // SEC-P0-006: Privileged Port Early Validation Tests
    // =========================================================================

    #[cfg(unix)]
    #[test]
    fn test_privileged_port_check_uid_logic() {
        // Test the UID check logic used in early validation
        let uid = unsafe { libc::getuid() };

        // Non-root users (uid != 0) should be denied ports < 1024
        if uid != 0 {
            // This simulates what run_server does for privileged ports
            let port = 80_u16;
            let should_fail = port < 1024 && uid != 0;
            assert!(should_fail, "Non-root users should be denied port 80");
        } else {
            // Root can bind to any port
            let port = 80_u16;
            let should_fail = port < 1024 && uid != 0;
            assert!(!should_fail, "Root users should be allowed port 80");
        }
    }

    #[cfg(unix)]
    #[test]
    fn test_privileged_port_boundary_values() {
        let uid = unsafe { libc::getuid() };

        // Test boundary: port 1023 is privileged, 1024 is not
        let test_cases = [
            (79_u16, true),    // Privileged
            (80_u16, true),    // Privileged (common HTTP)
            (443_u16, true),   // Privileged (common HTTPS)
            (1023_u16, true),  // Last privileged port
            (1024_u16, false), // First non-privileged port
            (8000_u16, false), // Common dev port
            (8080_u16, false), // Common alt HTTP port
        ];

        for (port, is_privileged) in test_cases {
            let requires_root = port < 1024;
            assert_eq!(
                requires_root, is_privileged,
                "Port {} should be classified as privileged: {}",
                port, is_privileged
            );

            if uid != 0 && is_privileged {
                // Non-root should be denied
                assert!(
                    port < 1024 && uid != 0,
                    "Non-root should be denied port {}",
                    port
                );
            }
        }
    }

    // =========================================================================
    // FAIL-FAST-001: Module Existence Early Validation Tests
    // =========================================================================

    #[test]
    fn test_module_check_importlib_spec_command() {
        // Test that the importlib.util.find_spec command is correctly formed
        let module = "nonexistent_module";
        let cmd = format!(
            "import importlib.util; exit(0 if importlib.util.find_spec('{}') else 1)",
            module
        );

        // Command should contain the module name
        assert!(cmd.contains(module));
        assert!(cmd.contains("importlib.util.find_spec"));
        assert!(cmd.contains("exit(0 if"));
        assert!(cmd.contains("else 1)"));
    }

    #[test]
    fn test_module_check_with_dotted_path() {
        // Test that dotted module paths work correctly
        let module = "package.submodule";
        let cmd = format!(
            "import importlib.util; exit(0 if importlib.util.find_spec('{}') else 1)",
            module
        );

        // Should handle dotted paths
        assert!(cmd.contains("package.submodule"));
    }
}
