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
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::mpsc::{self, Receiver, Sender};
use std::time::{Duration, Instant};

use anyhow::{Context, Result};

use crate::config::VeloConfig;
use crate::zygote::ZygoteLauncher;

// =============================================================================
// P1-3: WorkerPool - Prevents concurrent fork races via semaphore
// =============================================================================

/// Worker pool with semaphore-based concurrency control
///
/// This prevents concurrent fork races by limiting the number of
/// simultaneous Zygote forks. Uses atomic counter as a lightweight semaphore.
#[derive(Debug)]
pub struct WorkerPool {
    /// Maximum concurrent workers
    max_concurrent: usize,
    /// Current active worker count (atomic for thread-safety)
    active: Arc<AtomicUsize>,
}

impl WorkerPool {
    /// Create a new worker pool with specified concurrency limit
    pub fn new(max_concurrent: usize) -> Self {
        Self {
            max_concurrent: max_concurrent.max(1),
            active: Arc::new(AtomicUsize::new(0)),
        }
    }

    /// Try to acquire a permit. Returns None if pool is at capacity.
    pub fn try_acquire(&self) -> Option<WorkerPermit> {
        loop {
            let current = self.active.load(Ordering::SeqCst);
            if current >= self.max_concurrent {
                return None;
            }
            if self
                .active
                .compare_exchange(current, current + 1, Ordering::SeqCst, Ordering::SeqCst)
                .is_ok()
            {
                return Some(WorkerPermit {
                    active: Arc::clone(&self.active),
                });
            }
            // CAS failed, retry
        }
    }

    /// Acquire a permit, blocking until available
    pub fn acquire(&self) -> WorkerPermit {
        loop {
            if let Some(permit) = self.try_acquire() {
                return permit;
            }
            // Spin wait with backoff
            std::thread::sleep(Duration::from_micros(100));
        }
    }

    /// Get current active worker count
    pub fn active_count(&self) -> usize {
        self.active.load(Ordering::SeqCst)
    }

    /// Get maximum concurrent workers
    pub fn max_concurrent(&self) -> usize {
        self.max_concurrent
    }
}

/// RAII permit that releases on drop
#[derive(Debug)]
pub struct WorkerPermit {
    active: Arc<AtomicUsize>,
}

impl Drop for WorkerPermit {
    fn drop(&mut self) {
        self.active.fetch_sub(1, Ordering::SeqCst);
    }
}

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
/// - P1-3: Concurrent fork races - WorkerPool semaphore
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
    /// P1-3: Worker pool for concurrency control
    pool: WorkerPool,
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
            pool: WorkerPool::new(max_workers),
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

    // P1-3: WorkerPool tests

    #[test]
    fn test_worker_pool_creation() {
        let pool = WorkerPool::new(4);
        assert_eq!(pool.max_concurrent(), 4);
        assert_eq!(pool.active_count(), 0);
    }

    #[test]
    fn test_worker_pool_acquire_release() {
        let pool = WorkerPool::new(2);
        assert_eq!(pool.active_count(), 0);

        {
            let _permit1 = pool.acquire();
            assert_eq!(pool.active_count(), 1);

            let _permit2 = pool.acquire();
            assert_eq!(pool.active_count(), 2);
        } // permits drop here

        assert_eq!(pool.active_count(), 0);
    }

    #[test]
    fn test_worker_pool_try_acquire_at_capacity() {
        let pool = WorkerPool::new(1);

        let permit1 = pool.try_acquire();
        assert!(permit1.is_some());
        assert_eq!(pool.active_count(), 1);

        // Pool at capacity, should fail
        let permit2 = pool.try_acquire();
        assert!(permit2.is_none());
        assert_eq!(pool.active_count(), 1);

        // Drop permit1, should allow new acquire
        drop(permit1);
        let permit3 = pool.try_acquire();
        assert!(permit3.is_some());
    }

    #[test]
    fn test_worker_pool_min_capacity() {
        // Pool should have minimum capacity of 1
        let pool = WorkerPool::new(0);
        assert_eq!(pool.max_concurrent(), 1);
    }
}
