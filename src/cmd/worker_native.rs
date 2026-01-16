//! Handle 'velo worker-native' hidden command
//!
//! This command is used by the Host to spawn native workers via exec()
//! to avoid multi-threaded fork() issues.

use anyhow::Result;
use clap::Parser;
use std::path::PathBuf;

use crate::granian::config::WorkerConfig;
use crate::granian::worker_entry;

/// Native Worker Launcher (Hidden)
#[derive(Parser, Debug)]
#[command(name = "worker-native", hide = true)]
pub struct WorkerNativeCmd {
    /// Worker ID
    #[arg(long)]
    pub worker_id: i32,

    /// Socket FD to use for listening
    #[arg(long)]
    pub fd: i32,

    /// App path (module:app)
    #[arg(long)]
    pub app: String,

    /// Project directory
    #[arg(long)]
    pub project_dir: PathBuf,
}

/// Handle 'velo worker-native' command
pub fn cmd_worker_native(args: &[String]) -> Result<()> {
    // RFC-0020: Every velo process must initialize structured logging.
    let _ = env_logger::try_init();

    // Parse with clap - skip "velo" prefix
    let cmd = WorkerNativeCmd::try_parse_from(&args[1..])?;

    // 1. Reset signal handlers to defaults (already in a clean process, but for consistency)
    worker_entry::reset_signal_handlers();

    // 2. Strict FD Hygiene: Force close any inherited FDs except the listener and standard ones.
    // This is critical for Native Sovereignty and security.
    worker_entry::close_range_except(&[cmd.fd]);

    // 3. Prepare worker config
    let g_config = WorkerConfig::new(cmd.worker_id, cmd.fd, &cmd.app)
        .with_project_dir(cmd.project_dir)
        .with_websockets(true)
        .with_http_mode("auto");

    // 3. Run worker (blocks until completion)
    worker_entry::run_worker(g_config)?;

    Ok(())
}
