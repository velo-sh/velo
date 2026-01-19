//! VtestCoordinator - Orchestrates Zygote-accelerated test execution
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

use indicatif::{ProgressBar, ProgressStyle};
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
pub struct VtestResult {
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
pub struct VtestReport {
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
    pub results: Vec<VtestResult>,
}

impl VtestReport {
    /// Check if all tests passed
    pub fn all_passed(&self) -> bool {
        self.failed == 0
    }

    /// Get exit code (0 if all passed, 1 otherwise)
    pub fn exit_code(&self) -> i32 {
        if self.all_passed() { 0 } else { 1 }
    }
}

// =============================================================================
// Helper Functions for Test Runner
// =============================================================================

/// Find the pytest_velo/runner.py script
///
/// Search order:
/// 1. VELO_TEST_RUNNER environment variable (explicit override)
/// 2. pytest_velo/runner.py relative to current directory
/// 3. pytest_velo/runner.py relative to CARGO_MANIFEST_DIR (dev builds)
fn find_test_runner() -> Result<PathBuf> {
    // 1. Explicit override
    if let Ok(path) = std::env::var("VELO_TEST_RUNNER") {
        let p = PathBuf::from(&path);
        if p.exists() {
            return Ok(p);
        }
    }

    // 2. Relative to current directory
    let cwd = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    let runner_in_cwd = cwd.join("pytest_velo").join("runner.py");
    if runner_in_cwd.exists() {
        return Ok(runner_in_cwd);
    }

    // 3. Relative to cargo manifest (dev builds)
    if let Ok(manifest_dir) = std::env::var("CARGO_MANIFEST_DIR") {
        let runner_in_manifest = PathBuf::from(manifest_dir)
            .join("pytest_velo")
            .join("runner.py");
        if runner_in_manifest.exists() {
            return Ok(runner_in_manifest);
        }
    }

    anyhow::bail!(
        "pytest_velo/runner.py not found. Set VELO_TEST_RUNNER env var or run from project root."
    )
}

/// Parse JSON result from test runner stdout
fn parse_runner_result(
    stdout_path: &PathBuf,
    test_id: &str,
    elapsed: Duration,
) -> Result<VtestResult> {
    let content = std::fs::read_to_string(stdout_path).context("Failed to read runner stdout")?;

    // Find JSON in output (may have other output before/after)
    let json_start = content.find('{');
    let json_end = content.rfind('}');

    if let (Some(start), Some(end)) = (json_start, json_end) {
        let json_str = &content[start..=end];
        let parsed: serde_json::Value =
            serde_json::from_str(json_str).context("Failed to parse runner JSON")?;

        return Ok(VtestResult {
            test_id: parsed["test_id"].as_str().unwrap_or(test_id).to_string(),
            passed: parsed["passed"].as_bool().unwrap_or(false),
            exit_code: parsed["exit_code"].as_i64().unwrap_or(1) as i32,
            duration_ms: parsed["duration_ms"]
                .as_f64()
                .map(|d| d as u64)
                .unwrap_or(elapsed.as_millis() as u64),
            stdout: parsed["stdout"].as_str().map(String::from),
            stderr: parsed["stderr"].as_str().map(String::from),
        });
    }

    // No JSON found, return fallback
    anyhow::bail!("No JSON found in runner output: {}", content)
}

/// VtestCoordinator - Manages Zygote-accelerated test execution
///
/// # P0 Safety Requirements (RFC-0028 §12)
///
/// - P0-1: Fixture leakage - handled by pytest_velo_fork_reinit in plugin
/// - P0-2: GIL deadlock - Zygote is single-threaded before fork
/// - P0-3: FD corruption - workers use atexit._clear() + os._exit()
/// - P1-3: Concurrent fork races - WorkerPool semaphore
#[allow(dead_code)] // Fields used in future Phase 2 implementation
pub struct VtestCoordinator {
    /// Zygote launcher for spawning workers
    zygote: ZygoteLauncher,
    /// Configuration
    config: VeloConfig,
    /// Socket path
    socket_path: PathBuf,
    /// Results receiver channel
    results_rx: Receiver<VtestResult>,
    /// Results sender (cloned to workers)
    results_tx: Sender<VtestResult>,
    /// Pending test items
    pending: Vec<String>,
    /// P1-3: Worker pool for concurrency control
    pool: WorkerPool,
}

impl VtestCoordinator {
    /// Create a new VtestCoordinator
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
        // Use daemon=true to disable the Python parent monitor.
        // The Rust coordinator manages the Zygote lifecycle directly.
        self.zygote
            .start(preload, None, true, &self.config)
            .context("Failed to start Zygote for test coordination")?;
        Ok(())
    }

    /// Add a single test item to the pending queue
    pub fn add_test(&mut self, test_id: String) -> Result<()> {
        self.pending.push(test_id);
        Ok(())
    }

    /// Add multiple test items to the pending queue
    pub fn add_tests(&mut self, test_ids: Vec<String>) {
        self.pending.extend(test_ids);
    }

    /// Dispatch a single test to a Zygote worker
    ///
    /// Uses real Zygote IPC via spawn_worker() to execute the test
    /// through pytest_velo/runner.py.
    pub fn dispatch(&mut self, test_id: &str) -> Result<()> {
        let result = self.dispatch_via_zygote(test_id)?;

        self.results_tx
            .send(result)
            .context("Failed to send test result")?;

        Ok(())
    }

    /// Internal: dispatch test via real Zygote fork
    fn dispatch_via_zygote(&mut self, test_id: &str) -> Result<VtestResult> {
        let start = Instant::now();

        // P1-3: Acquire worker permit for concurrency control
        let _permit = self.pool.acquire();

        log::debug!("Dispatching test via Zygote: {}", test_id);

        // Find the test runner script
        let runner_script = find_test_runner().context("Failed to find pytest_velo/runner.py")?;

        // Spawn worker via Zygote
        let handle = self
            .zygote
            .spawn_worker(
                &runner_script,
                &[test_id],
                false, // sync mode - wait for completion
                false, // no fast mode
                None,  // no bundle
                None,  // no project root override
                None,  // no bundle size limit
                None,  // no shm
                None,  // no env overrides
                &self.config,
            )
            .context("Failed to spawn test worker")?;

        // Wait for worker (wait() already flushes stdout/stderr internally)
        let exit_code = handle.wait().unwrap_or(1);

        // Parse result from worker stdout (JSON format)
        let result = if let Some(stdout_path) = handle.stdout_path() {
            parse_runner_result(stdout_path, test_id, start.elapsed()).unwrap_or_else(|e| {
                log::warn!("Failed to parse runner output: {}", e);
                VtestResult {
                    test_id: test_id.to_string(),
                    passed: exit_code == 0,
                    exit_code,
                    duration_ms: start.elapsed().as_millis() as u64,
                    stdout: None,
                    stderr: None,
                }
            })
        } else {
            VtestResult {
                test_id: test_id.to_string(),
                passed: exit_code == 0,
                exit_code,
                duration_ms: start.elapsed().as_millis() as u64,
                stdout: None,
                stderr: None,
            }
        };

        Ok(result)
    }

    /// Run all pending tests and collect results
    pub fn run_all(&mut self) -> Result<VtestReport> {
        let mut report = VtestReport::default();
        let total_start = Instant::now();

        // Dispatch all pending tests
        let tests: Vec<_> = self.pending.drain(..).collect();
        report.total = tests.len();

        // 3. Dispatch & Execution Loop (Phase 3)
        let pb = ProgressBar::new(report.total as u64);
        pb.set_style(
            ProgressStyle::default_bar()
                .template("{spinner:.green} [{elapsed_precise}] [{bar:40.cyan/blue}] {pos}/{len} ({eta}) {msg}")
                .unwrap()
                .progress_chars("#>-"),
        );

        for test_id in tests {
            pb.set_message(format!("Running {}", test_id));
            self.dispatch(&test_id)?;

            // Collect result immediately if it's sequential
            if let Ok(result) = self.results_rx.recv_timeout(Duration::from_millis(10)) {
                if result.passed {
                    report.passed += 1;
                } else {
                    report.failed += 1;
                }
                report.results.push(result);
                pb.inc(1);
            }
        }

        // Collect any remaining results (should be none if sequential)
        while report.results.len() < report.total {
            match self.results_rx.recv_timeout(Duration::from_secs(5)) {
                Ok(result) => {
                    if result.passed {
                        report.passed += 1;
                    } else {
                        report.failed += 1;
                    }
                    report.results.push(result);
                    pb.inc(1);
                }
                Err(mpsc::RecvTimeoutError::Timeout) => {
                    break;
                }
                Err(mpsc::RecvTimeoutError::Disconnected) => {
                    break;
                }
            }
        }

        pb.finish_with_message("Done");

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
        // Use temp directory to avoid read-only filesystem issues in sandboxed tests
        let temp_dir = tempfile::tempdir().unwrap();
        unsafe {
            std::env::set_var("VELO_SOCKET_DIR", temp_dir.path().to_str().unwrap());
        }
        let config = VeloConfig::from_env_only();
        let coordinator = VtestCoordinator::new(&config, 4);
        unsafe {
            std::env::remove_var("VELO_SOCKET_DIR");
        }
        assert!(coordinator.is_ok());
    }

    #[test]
    fn test_report_defaults() {
        let report = VtestReport::default();
        assert_eq!(report.total, 0);
        assert!(report.all_passed());
        assert_eq!(report.exit_code(), 0);
    }

    #[test]
    fn test_report_with_failure() {
        let report = VtestReport {
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
