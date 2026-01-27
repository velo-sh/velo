use serde::{Deserialize, Serialize};
use std::path::PathBuf;

/// Protocol constants driven by SSoT
pub mod constants {
    include!(concat!(env!("OUT_DIR"), "/constants.rs"));
}

/// Commands sent from Launcher to Zygote
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[cfg_attr(feature = "fuzz", derive(arbitrary::Arbitrary))]
#[serde(tag = "type")]
pub enum ZygoteCommand {
    /// Fork a new worker to execute a script
    Fork {
        script_path: PathBuf,
        /// Optional module name for `python -m` execution
        #[serde(default)]
        module: Option<String>,
        args: Vec<String>,
        /// Whether to return PID immediately without waiting for completion
        #[serde(default)]
        async_mode: bool,
        /// Optional path for stdout capture (worker writes here)
        #[serde(default)]
        stdout_path: Option<PathBuf>,
        /// Optional path for stderr capture (worker writes here)
        #[serde(default)]
        stderr_path: Option<PathBuf>,
        /// Optional path for exit code capture (worker writes here)
        #[serde(default)]
        exit_code_path: Option<PathBuf>,
        /// Whether to enable Fast Mode (bundle-accelerated imports)
        #[serde(default)]
        fast_mode: bool,
        /// Path to the bundle file for Fast Mode
        #[serde(default)]
        bundle_path: Option<PathBuf>,
        /// Project root directory
        #[serde(default)]
        project_root: Option<PathBuf>,
        /// Max bundle size limit
        #[serde(default)]
        max_bundle_size: Option<u64>,
        /// Environment variables to inject into the worker
        #[serde(default)]
        env: Box<std::collections::HashMap<String, String>>,
        /// Size of the shared memory segment (if shm_fd is passed)
        #[serde(default)]
        shm_size: Option<usize>,
        /// Correlation ID for tracing
        #[serde(default)]
        request_id: Option<String>,
    },
    /// Shutdown the Zygote process
    Shutdown,
    /// Query Zygote status
    Status {
        #[serde(default)]
        request_id: Option<String>,
    },
    /// Wait for a worker to exit
    WaitWorker {
        worker_pid: u32,
        #[serde(default)]
        timeout_secs: Option<u64>,
        #[serde(default)]
        request_id: Option<String>,
    },
    /// Send signal to a worker
    SignalWorker {
        worker_pid: u32,
        signal: i32,
        #[serde(default)]
        request_id: Option<String>,
    },
    /// Query worker status
    WorkerStatus {
        worker_pid: u32,
        #[serde(default)]
        request_id: Option<String>,
    },
    /// Capability handshake
    Handshake {
        version: u8,
        capabilities: Vec<String>,
        #[serde(default)]
        request_id: Option<String>,
    },
    /// SEC-005: Forensic Authentication Handshake
    Auth {
        secret: String,
        #[serde(default)]
        request_id: Option<String>,
    },
    /// Replenish the pre-forked worker pool (P2)
    ReplenishPool {
        target_count: usize,
        #[serde(default)]
        request_id: Option<String>,
    },
    /// Run a test and return result via IPC (RFC-0028 Full IPC)
    RunTest {
        test_id: String,
        runner_path: PathBuf,
        #[serde(default)]
        cov_path: Option<String>,
        #[serde(default)]
        env: Box<std::collections::HashMap<String, String>>,
        #[serde(default)]
        request_id: Option<String>,
    },
}

/// Responses sent from Zygote to Launcher
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[cfg_attr(feature = "fuzz", derive(arbitrary::Arbitrary))]
#[serde(tag = "type")]
pub enum ZygoteResponse {
    /// Zygote is ready to accept commands
    Ready,
    /// Generic acknowledgment of command receipt
    Ack,
    /// Zygote status information
    Status {
        /// Zygote process ID
        pid: u32,
        /// List of preloaded modules
        preload: Vec<String>,
        /// Preload state
        #[serde(default)]
        state: String,
        /// Current number of workers in the idle pool
        #[serde(default)]
        pool_count: usize,
        /// Current target pool size
        #[serde(default)]
        target_pool_size: usize,
    },
    /// A worker was successfully forked
    Forked {
        worker_pid: u32,
        /// Exit code (available in sync mode)
        #[serde(default)]
        exit_code: Option<i32>,
    },
    /// Worker exited with code
    WorkerExited { worker_pid: u32, exit_code: i32 },
    /// Worker status info
    WorkerInfo {
        worker_pid: u32,
        is_running: bool,
        uptime_secs: u64,
    },
    /// An error occurred
    Error { message: String },
    /// Handshake response
    Handshake {
        version: u8,
        capabilities: Vec<String>,
    },
    /// Test execution completed
    TestComplete {
        worker_pid: u32,
        test_id: String,
        passed: bool,
        exit_code: i32,
        duration_ms: u64,
        stdout: Option<String>,
        stderr: Option<String>,
    },
    /// H-Gov Optimization Error
    OptimizationError {
        optimization_id: String,
        message: String,
        #[serde(default)]
        worker_pid: Option<u32>,
        #[serde(default)]
        trace_id: Option<String>,
        #[serde(default)]
        context: std::collections::HashMap<String, String>,
    },
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_protocol_serialization_smoke() {
        let cmd = ZygoteCommand::Shutdown;
        let serialized = serde_json::to_string(&cmd).unwrap();
        assert!(serialized.contains("Shutdown"));
    }
}
