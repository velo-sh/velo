//! Vibe Engine Orchestrator (RFC-0029)
//!
//! Ties together Watcher, Reaper, Isolation, and Gateway.
//! Implements the sub-10ms "Miracle Fork".

use anyhow::{Context, Result, bail};
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
        let socket_path = target.with_extension("vibe.sock");
        Self {
            target,
            gateway: Arc::new(VibeGateway::new(gateway_addr)),
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

        // 3. Start Watcher
        let engine_handler = EngineHandler {
            engine: Arc::new(Mutex::new(self.clone())),
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

        // 4. Entering master loop (Greedy Reaper)
        loop {
            reaper::reap_zombies();
            tokio::time::sleep(std::time::Duration::from_millis(100)).await;
        }
    }

    async fn trigger_execution(&self) -> Result<()> {
        log::info!("Triggering Vibe execution...");

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

        // 4. Spawn worker in background
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
                            std::thread::sleep(std::time::Duration::from_millis(500));
                            if unsafe { libc::getppid() } != ppid {
                                unsafe { libc::_exit(0) };
                            }
                        }
                    });
                }

                // Initialize Python and capture result
                #[allow(deprecated)]
                // prepare_freethreaded_python is still often needed in forked child
                pyo3::prepare_freethreaded_python();

                #[allow(deprecated)]
                let result = Python::with_gil(|py| -> Value {
                    match (|| -> Result<Value, PyErr> {
                        let code = std::fs::read_to_string(&target).map_err(|e| {
                            PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string())
                        })?;

                        let globals = PyDict::new(py);
                        globals.set_item("__name__", "__main__")?;

                        // Capture stdout (RFC-0029 requirement for feedback)
                        let sys = py.import("sys")?;
                        let io = py.import("io")?;
                        let stdout = io.call_method0("StringIO")?;
                        sys.setattr("stdout", &stdout)?;

                        let c_code = CString::new(code).map_err(|e| {
                            PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string())
                        })?;

                        py.run(c_code.as_c_str(), Some(&globals), None)?;

                        let output: String = stdout.call_method0("getvalue")?.extract()?;

                        Ok(json!({
                            "status": "success",
                            "target": target.to_string_lossy(),
                            "timestamp": chrono::Utc::now().to_rfc3339(),
                            "output": output
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

                // Write result to Master natively
                let mut writer = unsafe { std::fs::File::from_raw_fd(w_fd) };
                let serialized = serde_json::to_vec(&result).unwrap_or_default();
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

                // Read result from child asynchronously
                let mut reader = unsafe { std::fs::File::from_raw_fd(r_fd) };

                // We use spawn_blocking for the file I/O to avoid blocking the reactor
                let read_res = tokio::task::spawn_blocking(move || {
                    let mut b = Vec::new();
                    reader.read_to_end(&mut b).map(|_| b)
                })
                .await
                .context("Worker read task panicked")?;

                if let Ok(data) = read_res
                    && !data.is_empty()
                    && let Ok(val) = serde_json::from_slice::<Value>(&data)
                {
                    VibeGateway::broadcast(val).await;
                }

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
    engine: Arc<Mutex<VibeEngine>>,
    handle: tokio::runtime::Handle,
}

impl WatchHandler for EngineHandler {
    fn on_change(&self, _path: &str) {
        let engine = self.engine.clone();
        self.handle.spawn(async move {
            let engine = engine.lock().await;
            if let Err(e) = engine.trigger_execution().await {
                log::error!("Vibe execution failed: {:?}", e);
            }
        });
    }
}
