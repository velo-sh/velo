use crate::zygote::ZygoteLauncher;
use crate::zygote::core_ipc;
use crate::zygote::error::Result;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::Mutex;

/// Parameters needed to restart a Zygote service.
#[derive(Clone, Debug)]
pub struct ZygoteStartParams {
    pub preload: Vec<String>,
    pub app_name: Option<String>,
    pub python_path: PathBuf,
    pub config: crate::config::VeloConfig,
}

/// ZygoteGuardian - Rust-side supervisor for the Python Zygote.
/// Monitors health, memory, and lifecycle to ensure HFT-grade stability.
pub struct ZygoteGuardian {
    socket_path: PathBuf,
    zygote_pid: Arc<Mutex<u32>>,
    heartbeat_interval: Duration,
    start_params: Option<ZygoteStartParams>,
}

impl ZygoteGuardian {
    pub fn new(socket_path: PathBuf, zygote_pid: u32, params: Option<ZygoteStartParams>) -> Self {
        Self {
            socket_path,
            zygote_pid: Arc::new(Mutex::new(zygote_pid)),
            heartbeat_interval: Duration::from_secs(5),
            start_params: params,
        }
    }

    /// Start the guardian in a background thread.
    /// This is synchronous to allow easy integration into CLI commands.
    pub fn start(self) -> Result<()> {
        let guardian = Arc::new(self);

        std::thread::spawn(move || {
            let rt = match tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
            {
                Ok(rt) => rt,
                Err(e) => {
                    log::error!("❌ Failed to create Guardian runtime: {}", e);
                    return;
                }
            };

            rt.block_on(async move {
                let pid = *guardian.zygote_pid.lock().await;
                log::info!("🛡️ Zygote Guardian started for PID {}", pid);

                loop {
                    tokio::time::sleep(guardian.heartbeat_interval).await;

                    let current_pid = *guardian.zygote_pid.lock().await;

                    if let Err(e) = guardian.check_health(current_pid).await {
                        log::error!("🚨 Zygote Health Check Failed (PID {}): {}.", current_pid, e);

                        if let Some(ref params) = guardian.start_params {
                            log::info!("🔄 Attempting emergency Zygote restart...");
                            // P1: Full Recovery Orchestration
                            if let Err(re) = guardian.perform_restart(params).await {
                                log::error!("❌ Emergency Restart Failed: {}", re);
                            } else {
                                // After a successful restart, a NEW guardian has been spawned
                                // by the launcher.start() call. This old one must terminate.
                                log::info!("✨ New Guardian took over. Old Guardian (monitoring PID {}) shutting down.", current_pid);
                                break;
                            }
                        } else {
                            log::warn!("⚠️ No restart parameters available. Guardian exiting.");
                            break;
                        }
                    }
                }
            });
        });

        Ok(())
    }

    async fn perform_restart(&self, params: &ZygoteStartParams) -> Result<()> {
        let mut launcher =
            ZygoteLauncher::new(self.socket_path.clone()).with_python(params.python_path.clone());

        let preload_refs: Vec<&str> = params.preload.iter().map(|s| s.as_str()).collect();

        // This will restart the Zygote and spawn a NEW guardian
        launcher.start(
            &preload_refs,
            params.app_name.as_deref(),
            true,
            &params.config,
        )?;

        // Update local PID so this monitor continues (or we could let this one die and a new one take over)
        if let Some(new_pid) = launcher.pid() {
            let mut pid_lock = self.zygote_pid.lock().await;
            *pid_lock = new_pid;
            log::info!("✅ Zygote successfully restored. New PID: {}", new_pid);
        }

        Ok(())
    }

    /// Perform a deep probe via IPC and check system resources.
    async fn check_health(&self, pid: u32) -> Result<()> {
        // 1. Process Liveness
        if !self.is_process_alive(pid) {
            return Err(crate::zygote::error::ZygoteError::ConnectionFailed(
                "Process died".to_string(),
            ));
        }

        // 2. RSS Memory Monitoring (P1)
        if let Some(rss) = self.get_rss(pid) {
            let rss_mb = rss / 1024 / 1024;
            if rss_mb > 1024 {
                // 1GB threshold for now
                log::warn!(
                    "⚠️ Zygote PID {} RSS high: {} MB. Possible memory leak.",
                    pid,
                    rss_mb
                );
            }
        }

        // 3. IPC Heartbeat & Pool Management (P2)
        match crate::zygote::get_status()? {
            core_ipc::ZygoteResponse::Status {
                pool_count,
                target_pool_size,
                ..
            } => {
                // Phase 15 P2: Rust-Driven Pool Orchestration
                if pool_count == 0 && target_pool_size > 0 {
                    log::warn!("🔥 Zygote Pool Depleted! Sending emergency replenishment command.");
                    self.send_replenish(target_pool_size).await?;
                } else if pool_count < (target_pool_size / 2) && pool_count < 2 {
                    // Early replenishment if pool is low (e.g. 1 worker left in a target-2 pool)
                    log::info!(
                        "⚡ Zygote Pool Low ({} / {}). Replenishing...",
                        pool_count,
                        target_pool_size
                    );
                    self.send_replenish(target_pool_size).await?;
                }
            }
            _ => {
                log::warn!("⚠️ Unexpected response from Zygote Status probe.");
            }
        }

        Ok(())
    }

    async fn send_replenish(&self, target: usize) -> Result<()> {
        let cmd = core_ipc::ZygoteCommand::ReplenishPool {
            target_count: target,
            request_id: Some(uuid::Uuid::now_v7().to_string()),
        };

        // We use the short-lived send_command helper for management
        match core_ipc::send_command(&self.socket_path, cmd, None) {
            Ok(core_ipc::ZygoteResponse::Ack) => Ok(()),
            Ok(other) => {
                log::error!("❌ Pool Replenishment failed: {:?}", other);
                Err(crate::zygote::error::ZygoteError::ProtocolError(
                    "Replenish failed".to_string(),
                ))
            }
            Err(e) => Err(e),
        }
    }

    /// Get Resident Set Size (RSS) for the Zygote process.
    fn get_rss(&self, _pid: u32) -> Option<u64> {
        #[cfg(target_os = "macos")]
        {
            // Note: Modern libc crate might not expose proc_taskinfo easily.
            // Using a simplified check or parsing 'ps' as fallback if needed.
            // For now, return None to avoid compilation complexity in this pass,
            // but the logic is stubbed for forensic refinement.
            None
        }
        #[cfg(target_os = "linux")]
        {
            if let Ok(statm) = std::fs::read_to_string(format!("/proc/{}/statm", _pid)) {
                let parts: Vec<&str> = statm.split_whitespace().collect();
                if parts.len() > 1 {
                    if let Ok(rss_pages) = parts[1].parse::<u64>() {
                        return Some(rss_pages * 4096); // Assuming 4KB pages
                    }
                }
            }
            None
        }
        #[cfg(not(any(target_os = "macos", target_os = "linux")))]
        {
            None
        }
    }

    /// Low-level process check
    fn is_process_alive(&self, pid: u32) -> bool {
        #[cfg(unix)]
        {
            unsafe { libc::kill(pid as i32, 0) == 0 }
        }
        #[cfg(not(unix))]
        {
            true
        }
    }
}
