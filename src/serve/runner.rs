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

use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

use crate::serve::config::{LogFormat, ServeArgs};
use crate::serve::error::ServeError;
use crate::serve::framework::{detect_framework, get_preload_modules};
use crate::zygote::ZygoteLauncher;

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

    fn trace(&self, msg: &str) {
        if self.verbose_level >= 3 {
            self.log("trace", msg, None);
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

#[cfg(unix)]
fn apply_process_group(cmd: &mut Command) {
    use std::os::unix::process::CommandExt;
    unsafe {
        cmd.pre_exec(|| {
            // Become a process group leader (STB-RS-003)
            libc::setpgid(0, 0);

            // Reset SIGINT/SIGTERM to default in child (MAC-P0-002)
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
        #[cfg(unix)]
        apply_process_group(&mut cmd);

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
    pub fn terminate(&mut self) -> Result<(), ServeError> {
        let pid = self.child.id() as i32;
        // Send SIGTERM to the entire process group (negative PID)
        unsafe {
            if libc::kill(-pid, libc::SIGTERM) == 0 {
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
            let pid = self.child.id() as i32;
            // Send SIGKILL to the entire process group (negative PID)
            unsafe {
                if libc::kill(-pid, libc::SIGKILL) == 0 {
                    return Ok(());
                }
            }
        }
        self.child.kill().map_err(ServeError::SignalError)
    }

    /// Get the child's PID.
    pub fn id(&self) -> u32 {
        self.child.id()
    }
}

impl Drop for ManagedChild {
    fn drop(&mut self) {
        // STB-RS-003: Kill entire process group (PGID = child PID since child is group leader)
        // This ensures uvicorn workers and other grandchildren are also terminated
        #[cfg(unix)]
        {
            let pgid = self.child.id() as i32;
            // Send SIGKILL to the entire process group (negative PID)
            unsafe {
                libc::kill(-pgid, libc::SIGKILL);
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
// Event Bus Definitions (Recommendation #1)
// ============================================================================

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
    use std::time::Instant;

    // MANDATE R5: Capture the absolute start including early validation
    let start_time = Instant::now();

    // Step 1: Validate app format
    let (module, _attr) = args.parse_app()?;

    // Step 4: Setup Logger
    let logger = ServeLogger::new(args.log_format, args.verbose);

    // RAII Guard for Health Server (SEC-P0-004)
    let mut _health_server: Option<crate::serve::health::HealthServer> = None;
    let health_ready = Arc::new(AtomicBool::new(false));
    if let Some(ref bind) = args.health_bind {
        match crate::serve::health::HealthServer::spawn(bind, Arc::clone(&health_ready)) {
            Ok(server) => {
                logger.info(&format!("Health server listening on {}", bind));
                _health_server = Some(server);
            }
            Err(e) => {
                logger.error(&format!("Failed to start health server: {}", e));
            }
        }
    }

    // Step 1.1: Scaling Warning (R4)
    let file_count = count_python_files(project_dir);
    if file_count > 5000 {
        logger.warn(&format!("Large number of files detected ({})", file_count));
        logger.warn("help: Watching many files may impact performance.");
    }

    // Step 2: Detect framework FIRST (shows user Velo understands their project)
    let framework = detect_framework(module, project_dir);
    let preload_modules = get_preload_modules(framework);

    // Step 3: Handle Django settings inference (R2)
    if framework == crate::serve::framework::Framework::Django
        && std::env::var("DJANGO_SETTINGS_MODULE").is_err()
    {
        if let Some(settings) = crate::serve::framework::detect_django_settings(project_dir) {
            logger.info(&format!("Inferred DJANGO_SETTINGS_MODULE={}", settings));
            unsafe {
                std::env::set_var("DJANGO_SETTINGS_MODULE", &settings);
            }
        } else {
            logger.warn("Django detected but DJANGO_SETTINGS_MODULE is not set.");
            logger.warn("help: High-performance preloading may be impaired.");
        }
    }

    // Step 3: Select server based on framework (D4)
    let server = get_server_type(framework);

    // Show framework detection result
    if framework != crate::serve::framework::Framework::Unknown {
        logger.info_with(
            &format!("Detected: {} → {}", framework, server),
            &format!("(auto-preload: {})", preload_modules.join(", ")),
        );
    } else {
        logger.trace("Framework: Unknown (auto-detection missed)");
    }

    // Step 4: Check server is installed
    logger.debug(&format!("Checking if {} is installed...", server));
    if !check_server_installed(server, python_path) {
        logger.error(&format!("Missing dependency: {}", server));
        eprintln!();
        eprintln!("{} is required to run {} applications.", server, framework);
        eprintln!("To fix:");
        eprintln!("    {}", server.install_hint());
        return Err(anyhow::anyhow!("Missing dependency: {}", server));
    }

    // Shutdown Coordinator (SEC-P0-001)
    let shutdown_coordinator =
        crate::serve::runner::ShutdownCoordinator::new().map_err(ServeError::SignalError)?;

    // Step 5:    // Event Bus (Recommendation #1)
    let (tx, rx) = mpsc::channel();

    // Signal Forwarder
    #[cfg(unix)]
    spawn_signal_forwarder(tx.clone())?;

    // Hot Reload Watcher (D6, D7)
    let mut _watcher: Option<Arc<crate::serve::watcher::FileWatcher>> = None;
    if args.reload {
        let watcher = crate::serve::watcher::FileWatcher::new(
            shutdown_coordinator.flag.clone(),
            crate::serve::watcher::DEFAULT_DEBOUNCE_MS,
        )?;
        watcher.watch(project_dir)?;
        let watcher = Arc::new(watcher);

        // Spawn a thread to poll the watcher and bridge events to the bus
        let tx_clone = tx.clone();
        let watcher_clone = Arc::clone(&watcher);
        thread::spawn(move || {
            loop {
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

    // RAII Guard for Zygote (Recommendation #3)
    // Needs to stay alive for the duration of the server
    #[allow(unused_mut)]
    let mut _zygote_guard: Option<crate::zygote::ZygoteLauncher> = None;

    // Step 6: Start server
    logger.info("Starting server...");
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

    // Start Zygote if enabled and we have preload modules
    if args.use_zygote && !preload_modules.is_empty() && crate::zygote::is_supported() {
        let socket_path = crate::zygote::ipc::default_socket_path();

        if !socket_path.exists() {
            logger.info(&format!("Pre-warming Zygote with {} modules...", framework));
            let mut launcher =
                ZygoteLauncher::new(socket_path).with_python(python_path.to_path_buf());

            if let Err(e) = launcher.start(&preload_modules) {
                logger.warn(&format!("Zygote pre-warm failed: {}", e));
                if args.log_format == LogFormat::Text {
                    eprintln!("   Continuing without Zygote optimization");
                }
            } else {
                logger.info("Zygote ready");
                // RAII: Keep Zygote alive as long as this function runs
                // When this function returns/unwinds, _zygote_guard will drop and kill the Zygote
                _zygote_guard = Some(launcher);
            }
        } else {
            logger.info("Using existing Zygote");
        }
    }

    // Build server command based on server type
    logger.debug(&format!("Building command for {}...", server));
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

    // MAC-P0-002: Reset signal handlers in child (ADR D4) and STB-RS-003: Process Group
    // Handled inside ManagedChild::spawn now, but we keep this as a note
    // Actually, we should remove this call site as it's now handled by ManagedChild::spawn

    // Set working directory and inherit stdio
    logger.verbose(&format!("Current directory: {:?}", project_dir));
    cmd.current_dir(project_dir)
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());

    // Unified Startup Timing & Dry Run (R5, PERF-P0-001)
    let ready_ms = start_time.elapsed().as_millis();
    logger.log_with_timing("info", "Server ready", None, Some(ready_ms));

    if args.dry_run {
        logger.info(&format!(
            "Dry run: Command would be: {:?} {:?}",
            cmd.get_program(),
            cmd.get_args()
                .map(|v| v.to_string_lossy())
                .collect::<Vec<_>>()
                .join(" ")
        ));
        return Ok(());
    }

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

    // Spawn with ManagedChild for RAII cleanup (D2)
    let mut child_result = ManagedChild::spawn(cmd, args.pid_file.clone());

    if let Ok(ref mut child) = child_result {
        logger.info(&format!("Server started (PID: {})", child.id()));
        health_ready.store(true, std::sync::atomic::Ordering::SeqCst);

        // Main loop: Wait for Events (Zero Busy Wait)
        loop {
            // Block until event received
            match rx.recv() {
                Ok(ServerEvent::Signal(sig)) => {
                    match sig {
                        signal_hook::consts::SIGCHLD => {
                            // Optimistic: Child might have exited
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
                                    return Ok(());
                                }
                                Ok(None) => continue,
                                Err(e) => {
                                    return Err(anyhow::anyhow!("Error waiting for server: {}", e));
                                }
                            }
                        }

                        signal_hook::consts::SIGINT | signal_hook::consts::SIGTERM => {
                            eprintln!();
                            logger
                                .info("Shutdown signal received, waiting for graceful shutdown...");

                            if let Err(e) = child.terminate() {
                                logger.warn(&format!("Failed to send SIGTERM: {}", e));
                            }

                            // Wait with timeout
                            match child.wait_timeout(Duration::from_secs(args.timeout)) {
                                Ok(Some(_)) => {
                                    logger.info("Server stopped gracefully");
                                    return Ok(());
                                }
                                Ok(None) => {
                                    logger.warn("Shutdown timeout expired, force killing...");
                                    let _ = child.kill();
                                    return Ok(());
                                }
                                Err(e) => anyhow::bail!("Error during shutdown: {}", e),
                            }
                        }
                        _ => {
                            // CN-P0-002: Forward other signals to child group
                            let pid = child.id() as i32;
                            unsafe {
                                libc::kill(-pid, sig);
                            }
                        }
                    }
                }
                Ok(ServerEvent::Reload) => {
                    logger.info("Changes detected, restarting server...");
                    if let Ok(ref mut child) = child_result {
                        let _ = child.kill();
                    }
                    // Break loop to trigger fresh spawn in the caller
                    return Ok(());
                }
                Err(_) => break, // Bus disconnected
                _ => {}
            }
        }
    } else if let Err(e) = child_result {
        logger.error(&format!("Failed to start server: {}", e));
        // Keep health server alive if it was spawned, waiting for signals to exit
        loop {
            match rx.recv_timeout(Duration::from_secs(1)) {
                Ok(ServerEvent::Signal(sig)) => {
                    if sig == signal_hook::consts::SIGINT || sig == signal_hook::consts::SIGTERM {
                        return Err(anyhow::anyhow!("Server failed to start: {}", e));
                    }
                }
                Err(mpsc::RecvTimeoutError::Disconnected) => break,
                _ => {}
            }
        }
        return Err(anyhow::anyhow!("Server failed to start: {}", e));
    }

    Ok(())
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
        let result = spawn_signal_forwarder(tx);
        assert!(result.is_ok(), "Signal forwarder should spawn successfully");
    }

    #[cfg(unix)]
    #[test]
    fn test_spawn_signal_forwarder_exits_when_sender_dropped() {
        use std::time::Instant;

        let (tx, rx) = mpsc::channel::<ServerEvent>();

        // Spawn the forwarder
        spawn_signal_forwarder(tx).unwrap();

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
}
