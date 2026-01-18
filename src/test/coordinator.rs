//! TestCoordinator - Orchestrates Zygote-accelerated test execution
//!
//! RFC-0028: Phase 2 Implementation
//!
//! This coordinator manages a pool of Zygote workers and dispatches
//! test items for execution via COW forks.
//!
//! # Architecture
//!
//! ```text
//! ┌─────────────────────────────────────────────────────────────┐
//! │                    TestCoordinator                          │
//! ├─────────────────────────────────────────────────────────────┤
//! │  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
//! │  │   pytest    │───▶│ Coordinator │───▶│   Zygote    │     │
//! │  │  (collect)  │    │   (Rust)    │    │  (workers)  │     │
//! │  └─────────────┘    └─────────────┘    └─────────────┘     │
//! └─────────────────────────────────────────────────────────────┘
//! ```

use std::path::PathBuf;
use std::sync::mpsc::{self, Receiver, Sender};
use std::time::{Duration, Instant};

use anyhow::{Context, Result};

use crate::config::VeloConfig;
use crate::zygote::ZygoteLauncher;

/// Result of a single test execution
#[derive(Debug, Clone)]
pub struct TestResult {
    /// Test item ID (e.g., "tests/test_foo.py::test_bar")
    pub test_id: String,
    /// Whether the test passed
    pub passed: bool,
    /// Exit code from the worker
    pub exit_code: i32,
    /// Execution time in milliseconds
    pub duration_ms: u64,
    /// Captured stdout (if any)
    pub stdout: Option<String>,
    /// Captured stderr (if any)
    pub stderr: Option<String>,
}

/// Aggregated test report
#[derive(Debug, Default)]
pub struct TestReport {
    /// Total tests run
    pub total: usize,
    /// Passed tests
    pub passed: usize,
    /// Failed tests
    pub failed: usize,
    /// Skipped tests
    pub skipped: usize,
    /// Total execution time in milliseconds
    pub total_duration_ms: u64,
    /// Individual test results
    pub results: Vec<TestResult>,
}

impl TestReport {
    /// Check if all tests passed
    pub fn all_passed(&self) -> bool {
        self.failed == 0
    }

    /// Get exit code (0 if all passed, 1 otherwise)
    pub fn exit_code(&self) -> i32 {
        if self.all_passed() { 0 } else { 1 }
    }
}

/// TestCoordinator - Manages Zygote-accelerated test execution
///
/// # P0 Safety Requirements (RFC-0028 §12)
///
/// - P0-1: Fixture leakage - handled by pytest_velo_fork_reinit in plugin
/// - P0-2: GIL deadlock - Zygote is single-threaded before fork
/// - P0-3: FD corruption - workers use atexit._clear() + os._exit()
#[allow(dead_code)] // Fields used in future Phase 2 implementation
pub struct TestCoordinator {
    /// Zygote launcher for spawning workers
    zygote: ZygoteLauncher,
    /// Configuration
    config: VeloConfig,
    /// Socket path
    socket_path: PathBuf,
    /// Results receiver channel
    results_rx: Receiver<TestResult>,
    /// Results sender (cloned to workers)
    results_tx: Sender<TestResult>,
    /// Pending test items
    pending: Vec<String>,
    /// Active worker count
    active_workers: usize,
    /// Maximum concurrent workers
    max_workers: usize,
}

impl TestCoordinator {
    /// Create a new TestCoordinator
    ///
    /// # Arguments
    /// * `config` - Velo configuration
    /// * `max_workers` - Maximum number of concurrent workers (default: 1)
    pub fn new(config: &VeloConfig, max_workers: usize) -> Result<Self> {
        let socket_path = crate::zygote::core_ipc::default_socket_path();
        let zygote = ZygoteLauncher::new(socket_path.clone());
        let (results_tx, results_rx) = mpsc::channel();

        Ok(Self {
            zygote,
            config: config.clone(),
            socket_path,
            results_rx,
            results_tx,
            pending: Vec::new(),
            active_workers: 0,
            max_workers: max_workers.max(1),
        })
    }

    /// Start the Zygote if not already running
    ///
    /// # Arguments
    /// * `preload` - Modules to preload in Zygote
    pub fn ensure_zygote(&mut self, preload: &[&str]) -> Result<()> {
        self.zygote
            .start(preload, None, false, &self.config)
            .context("Failed to start Zygote for test coordination")?;
        Ok(())
    }

    /// Add test items to the pending queue
    pub fn add_tests(&mut self, test_ids: Vec<String>) {
        self.pending.extend(test_ids);
    }

    /// Dispatch a single test to a Zygote worker
    ///
    /// This is a placeholder - full implementation requires IPC protocol
    /// extension to support test dispatch commands.
    pub fn dispatch(&mut self, test_id: &str) -> Result<()> {
        let start = Instant::now();

        // TODO: Implement actual Zygote fork dispatch
        // For now, this is a stub that simulates dispatch
        //
        // Full implementation would:
        // 1. Send a FORK command with test_id to Zygote
        // 2. Zygote forks a worker running the specific test
        // 3. Worker reports result back via IPC
        // 4. Result is sent through results_tx channel

        log::debug!("Dispatching test: {}", test_id);

        // Simulate result for now
        let result = TestResult {
            test_id: test_id.to_string(),
            passed: true,
            exit_code: 0,
            duration_ms: start.elapsed().as_millis() as u64,
            stdout: None,
            stderr: None,
        };

        self.results_tx
            .send(result)
            .context("Failed to send test result")?;

        Ok(())
    }

    /// Run all pending tests and collect results
    pub fn run_all(&mut self) -> Result<TestReport> {
        let mut report = TestReport::default();
        let total_start = Instant::now();

        // Dispatch all pending tests
        let tests: Vec<_> = self.pending.drain(..).collect();
        report.total = tests.len();

        for test_id in tests {
            self.dispatch(&test_id)?;
        }

        // Collect all results
        while report.results.len() < report.total {
            match self.results_rx.recv_timeout(Duration::from_secs(30)) {
                Ok(result) => {
                    if result.passed {
                        report.passed += 1;
                    } else {
                        report.failed += 1;
                    }
                    report.results.push(result);
                }
                Err(mpsc::RecvTimeoutError::Timeout) => {
                    log::warn!("Timeout waiting for test results");
                    break;
                }
                Err(mpsc::RecvTimeoutError::Disconnected) => {
                    break;
                }
            }
        }

        report.total_duration_ms = total_start.elapsed().as_millis() as u64;
        Ok(report)
    }

    /// Stop the Zygote
    pub fn shutdown(&mut self) -> Result<()> {
        self.zygote.stop().context("Failed to stop Zygote")?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_coordinator_creation() {
        let config = VeloConfig::from_env_only();
        let coordinator = TestCoordinator::new(&config, 4);
        assert!(coordinator.is_ok());
    }

    #[test]
    fn test_report_defaults() {
        let report = TestReport::default();
        assert_eq!(report.total, 0);
        assert!(report.all_passed());
        assert_eq!(report.exit_code(), 0);
    }

    #[test]
    fn test_report_with_failure() {
        let report = TestReport {
            total: 2,
            passed: 1,
            failed: 1,
            ..Default::default()
        };
        assert!(!report.all_passed());
        assert_eq!(report.exit_code(), 1);
    }
}
