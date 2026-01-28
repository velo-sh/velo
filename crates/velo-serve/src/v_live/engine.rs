//! Vibe Engine Orchestrator (RFC-0029)
//!
//! Ties together Watcher, Reaper, Isolation, and Gateway.
//! Implements the sub-10ms "Miracle Fork".

use anyhow::{Context, Result, bail};
use futures_util::FutureExt;
use nix::unistd::{ForkResult, fork, pipe};
use pyo3::prelude::*;
use pyo3::types::PyDict;
use serde_json::{Value, json};
use std::ffi::CString;
use std::io::{Read, Write};
use std::os::unix::io::FromRawFd;
use std::path::PathBuf;
use std::sync::Arc;
use tokio::sync::Mutex;

use crate::v_live::gateway::VibeGateway;
use crate::v_live::isolation::PipeFence;
use crate::v_live::reaper;
use crate::v_live::watcher::{VibeWatcher, WatchHandler};

#[derive(Clone)]
pub struct VibeEngine {
    target: PathBuf,
    gateway: Arc<VibeGateway>,
    fence: Arc<PipeFence>,
    current_worker: Arc<Mutex<Option<libc::pid_t>>>,
}

impl VibeEngine {
    pub fn new(target: PathBuf, gateway_addr: &str) -> Self {
        let target_file_name = target
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("vibe");
        let socket_path = target.with_file_name(format!(".{}.vibe.sock", target_file_name));
        let target_clone = target.clone();
        Self {
            target,
            gateway: Arc::new(VibeGateway::new(gateway_addr, target_clone)),
            fence: Arc::new(PipeFence::new(socket_path)),
            current_worker: Arc::new(Mutex::new(None)),
        }
    }

    pub async fn start(&self) -> Result<()> {
        log::info!("Starting Vibe Engine for {:?}", self.target);

        // 1. Start Gateway
        let gateway = self.gateway.clone();
        tokio::spawn(async move {
            if let Err(e) = gateway.run().await {
                log::error!("Vibe Gateway failed: {:?}", e);
            }
        });

        // 2. Initial execution
        self.trigger_execution().await?;

        // 3. Start Debouncer Task
        let (tx, mut rx) = tokio::sync::mpsc::channel::<()>(32);
        let engine = self.clone();
        tokio::spawn(async move {
            let mut next_trigger: Option<tokio::time::Instant> = None;
            let quiescence = std::time::Duration::from_millis(200);

            loop {
                // We use a BoxFuture to select over a dynamic sleep/pending
                let sleep = if let Some(t) = next_trigger {
                    tokio::time::sleep_until(t).boxed()
                } else {
                    futures_util::future::pending().boxed()
                };

                tokio::select! {
                    biased;
                    _ = rx.recv() => {
                        next_trigger = Some(tokio::time::Instant::now() + quiescence);
                        // Drain channel to consolidate rapid events
                        while rx.try_recv().is_ok() {
                            next_trigger = Some(tokio::time::Instant::now() + quiescence);
                        }
                    }
                    _ = sleep => {
                        next_trigger = None;
                        let e = engine.clone();
                        tokio::spawn(async move {
                            if let Err(err) = e.trigger_execution().await {
                                log::error!("Vibe execution failed: {:?}", err);
                            }
                        });
                    }
                }
            }
        });

        // 4. Start Watcher
        let engine_handler = EngineHandler {
            tx,
            handle: tokio::runtime::Handle::current(),
        };
        let mut watcher = VibeWatcher::new(engine_handler);

        let mut watch_dir = self
            .target
            .parent()
            .unwrap_or(std::path::Path::new("."))
            .to_path_buf();
        if watch_dir.to_str().map(|s| s.is_empty()).unwrap_or(true) {
            watch_dir = std::path::PathBuf::from(".");
        }
        watcher.watch(watch_dir.to_str().unwrap())?;

        // 5. Entering master loop (Greedy Reaper)
        loop {
            reaper::reap_zombies();
            tokio::time::sleep(std::time::Duration::from_millis(100)).await;
        }
    }

    async fn trigger_execution(&self) -> Result<()> {
        log::info!("Triggering Vibe execution...");
        // ... (rest of implementation remains same)

        // 1. Greedy Reaper: Clean up any dead workers (Pillar 1)
        reaper::reap_zombies();

        // 2. Kill current worker if it's still running (Pillar 1: Prevent save storm overlap)
        {
            let mut worker = self.current_worker.lock().await;
            if let Some(pid) = *worker {
                log::debug!("Killing previous worker {}", pid);
                unsafe { libc::kill(pid, libc::SIGKILL) };
                *worker = None;
                reaper::reap_zombies();
            }
        }

        // 3. Pipe-Fence: Clear stale resources (Pillar 3)
        self.fence.cleanup()?;

        // 4. Clear last result from gateway cache to prevent stale push to late joiners
        VibeGateway::clear_last_result();

        // 5. Spawn worker in background
        // We use a separate task so the Master remains responsive to new events
        let engine = self.clone();
        tokio::spawn(async move {
            if let Err(e) = engine.miracle_fork().await {
                log::error!("Vibe worker failed: {:?}", e);
            }
        });

        Ok(())
    }

    async fn miracle_fork(&self) -> Result<()> {
        let target = self.target.clone();

        // 1. Set up communication pipe
        let (r_fd, w_fd) = pipe().context("Pipe failed")?;

        // 2. Miracle Fork (RFC-0029 Pillar 4)
        match unsafe { fork() } {
            Ok(ForkResult::Child) => {
                // Inside child: Close reader
                unsafe { libc::close(r_fd) };

                // DEF-08-010: Pipe-Fence (RFC-0029 Pillar 3 Hardening)
                // Attempt to lock the fence. If it fails, another worker is active or stale.
                if let Ok(locked) = self.fence.lock()
                    && !locked
                {
                    // This should be rare due to Master's SIGKILL management, but provides
                    // forensic-grade protection against process management leaks.
                    unsafe { libc::_exit(1) };
                }

                // ORPHAN PROTECTION (RFC-0029 Pillar 5)
                #[cfg(target_os = "linux")]
                unsafe {
                    libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGKILL);
                }

                #[cfg(target_os = "macos")]
                {
                    // Best effort orphan protection for macOS
                    let ppid = unsafe { libc::getppid() };
                    std::thread::spawn(move || {
                        loop {
                            std::thread::sleep(std::time::Duration::from_millis(20));
                            if unsafe { libc::getppid() } != ppid {
                                unsafe { libc::_exit(0) };
                            }
                        }
                    });
                }

                // DEF-08-011: Resource Capping (RFC-0029 Hardening)
                // We set hard limits on memory and CPU to prevent resource exhaustion.
                unsafe {
                    // 1GB Address Space (AS)
                    let mem_limit = 1024 * 1024 * 1024;
                    let rlimit_as = libc::rlimit {
                        rlim_cur: mem_limit,
                        rlim_max: mem_limit,
                    };
                    libc::setrlimit(libc::RLIMIT_AS, &rlimit_as);

                    // 10 Seconds CPU Time
                    let cpu_limit = 10;
                    let rlimit_cpu = libc::rlimit {
                        rlim_cur: cpu_limit,
                        rlim_max: cpu_limit,
                    };
                    libc::setrlimit(libc::RLIMIT_CPU, &rlimit_cpu);
                }

                // REDIRECT STDOUT/STDERR NATIVELY (RFC-0029 Pillar G1 Hardening)
                // We redirect to the pipe so native code output is captured.
                unsafe {
                    libc::dup2(w_fd, 1);
                    libc::dup2(w_fd, 2);
                }

                // SINC-002: Load .env file before Python execution (Environment Drift Fix)
                // Each fork() should pick up the latest .env values from disk.
                let project_dir = target.parent().unwrap_or(std::path::Path::new("."));
                let dotenv_path = project_dir.join(".env");
                if dotenv_path.exists()
                    && let Ok(content) = std::fs::read_to_string(&dotenv_path)
                {
                    for line in content.lines() {
                        let line = line.trim();
                        if line.is_empty() || line.starts_with('#') {
                            continue;
                        }
                        if let Some((key, value)) = line.split_once('=') {
                            // SAFETY: This is in a forked child before any threads
                            unsafe { std::env::set_var(key.trim(), value.trim()) };
                        }
                    }
                }

                // Initialize Python and capture result
                #[allow(deprecated)]
                // prepare_freethreaded_python is still often needed in forked child
                pyo3::prepare_freethreaded_python();

                #[allow(deprecated)]
                let result = Python::with_gil(|py| -> Value {
                    // SINC-001: Refresh Python import system for newly installed packages (Genotype Aging Fix)
                    // After fork, the parent's import cache is stale. We need to:
                    // 1. Detect the active venv's site-packages from VIRTUAL_ENV
                    // 2. Ensure it's in sys.path
                    // 3. Clear the path importer cache
                    // 4. Invalidate all finder caches
                    let refresh_code = r#"
import sys
import os
import site
import importlib
import glob

# Clear the path importer cache to force re-scanning
sys.path_importer_cache.clear()

# Invalidate caches in all meta path finders
importlib.invalidate_caches()

# Get the active venv's site-packages from VIRTUAL_ENV
venv = os.environ.get('VIRTUAL_ENV')
if venv:
    # Find site-packages in the venv (handles different Python versions)
    sp_pattern = os.path.join(venv, 'lib', 'python*', 'site-packages')
    matches = glob.glob(sp_pattern)
    for sp in matches:
        if sp not in sys.path:
            sys.path.insert(0, sp)
        # Re-add using addsitedir to process .pth files
        site.addsitedir(sp)

# Also refresh standard site-packages
for sp in site.getsitepackages():
    if os.path.exists(sp):
        site.addsitedir(sp)

# Final cache invalidation
importlib.invalidate_caches()
"#;
                    let _ = py.run(&CString::new(refresh_code).unwrap_or_default(), None, None);

                    match (|| -> Result<Value, PyErr> {
                        let code = std::fs::read_to_string(&target).map_err(|e| {
                            PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string())
                        })?;

                        let globals = PyDict::new(py);
                        globals.set_item("__name__", "__main__")?;

                        let c_code = CString::new(code).map_err(|e| {
                            PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string())
                        })?;

                        // Run the code. Standard output now goes directly to the pipe (w_fd).
                        py.run(c_code.as_c_str(), Some(&globals), None)?;

                        Ok(json!({
                            "status": "success",
                            "target": target.to_string_lossy(),
                            "timestamp": chrono::Utc::now().to_rfc3339(),
                            // Output is now handled by the native redirection and read by master
                        }))
                    })() {
                        Ok(val) => val,
                        Err(e) => json!({
                            "status": "error",
                            "error": format!("{:?}", e),
                            "target": target.to_string_lossy(),
                            "timestamp": chrono::Utc::now().to_rfc3339(),
                        }),
                    }
                });

                // Write metadata JSON as a single line at the end
                // The master will read the entire pipe. Anything before the last line is raw output.
                let mut writer = unsafe { std::fs::File::from_raw_fd(w_fd) };
                let mut serialized = serde_json::to_vec(&result).unwrap_or_default();
                serialized.push(b'\n');
                let _ = writer.write_all(&serialized);
                let _ = writer.flush();
                drop(writer);

                // BYPASS ALL CLEANUPS (The "Miracle" part)
                unsafe { libc::_exit(0) };
            }
            Ok(ForkResult::Parent { child }) => {
                let pid = child.as_raw();
                unsafe { libc::close(w_fd) };

                // Track child PID immediately for management
                {
                    let mut worker = self.current_worker.lock().await;
                    *worker = Some(pid);
                }

                // Read result from child in real-time to prevent pipe deadlocks (RFC-0029)
                let reader = unsafe { std::fs::File::from_raw_fd(r_fd) };

                tokio::task::spawn_blocking(move || {
                    let mut reader = reader;
                    let mut buffer = [0u8; 8192];
                    let mut captured_output = Vec::new();

                    loop {
                        match reader.read(&mut buffer) {
                            Ok(0) => break, // EOF
                            Ok(n) => {
                                captured_output.extend_from_slice(&buffer[..n]);

                                // Partial Broadcast: Scan for newlines to send early if needed
                                // (For now we just buffer and check for the final JSON line)
                            }
                            Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
                            Err(_) => break,
                        }
                    }

                    // Scan for the metadata JSON (last line)
                    let data = captured_output;
                    if data.is_empty() {
                        return;
                    }

                    let mut lines: Vec<&[u8]> = data.split(|&b| b == b'\n').collect();
                    if lines.last().is_some_and(|l| l.is_empty()) {
                        lines.pop();
                    }

                    if let Some(last_line) = lines.last()
                        && let Ok(mut val) = serde_json::from_slice::<Value>(last_line)
                    {
                        let mut output_bytes = Vec::new();
                        for line in lines.iter().take(lines.len() - 1) {
                            output_bytes.extend_from_slice(line);
                            output_bytes.push(b'\n');
                        }
                        let output = String::from_utf8_lossy(&output_bytes).to_string();

                        if let Some(obj) = val.as_object_mut() {
                            obj.insert("output".to_string(), json!(output));
                        }
                        VibeGateway::broadcast_sync(val);
                    }
                });

                // Since we moved to a detached task for reading, we don't await it here.
                // This ensures the Master loop remains responsive to new events.
                // We do still need to cleanup the PID tracking when the process is reaped.

                // Cleanup PID tracking when done
                let mut worker = self.current_worker.lock().await;
                if *worker == Some(pid) {
                    *worker = None;
                }
            }
            Err(e) => bail!("Fork failed: {:?}", e),
        }

        Ok(())
    }
}

struct EngineHandler {
    tx: tokio::sync::mpsc::Sender<()>,
    handle: tokio::runtime::Handle,
}

impl WatchHandler for EngineHandler {
    fn on_change(&self, _path: &str) {
        // PROACTIVE CACHE INVALIDATION (RFC-0029 Pillar 6)
        VibeGateway::clear_last_result();

        let tx = self.tx.clone();
        self.handle.spawn(async move {
            let _ = tx.send(()).await;
        });
    }
}
